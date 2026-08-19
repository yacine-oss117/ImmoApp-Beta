"""Distributed importer finalization orchestration and terminal-state truth."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from django.db import transaction
from django.utils import timezone

import server.services.import_execution_metrics as import_execution_metrics
import server.services.import_follow_up as import_follow_up
import server.services.import_job_topology as import_job_topology
import server.services.import_rebuild_handoff as import_rebuild_handoff
from server.imports.models import ImportChunkPhase, ImportJob
from server.services.import_notifications import (
    emit_import_notification,
    record_import_success_notification,
)
from server.services.import_progress_runtime import build_progress_detail
from server.services.import_review_runtime import (
    review_overflow_count,
    review_overflow_errors,
)
from server.services.import_review_store import (
    ReviewCountSnapshot,
    clear_db_review_state,
    compatibility_review_rows,
    persist_review_state_with_compatibility_sample,
    review_count_snapshot,
)
from server.services.import_types import ImportLoadOutcome, ImportResult, ReviewRows
from server.services.import_ui_summary import derive_terminal_result_state
from server.services.json_safe import json_safe_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportLoadRollup:
    result: ImportResult
    load_outcome: ImportLoadOutcome
    result_entity_counts: dict[str, int]
    total_db_time: float
    phase_count: int


@dataclass(frozen=True)
class ImportReviewRollup:
    phase_errors: list[dict[str, object]]
    review_snapshot: ReviewCountSnapshot
    visible_review_rows: list[dict[str, object]]
    review_count: int
    review_overflow_total: int
    review_total_count: int
    has_review_rows: bool


@dataclass(frozen=True)
class ImportTerminalDecision:
    status: str
    stage: str
    final_phase: str
    error_message: str | None
    terminal_status: str
    job_completed_successfully: bool


def _json_safe_dict(value: object) -> dict[str, object]:
    safe_value = json_safe_value(value)
    return dict(safe_value) if isinstance(safe_value, dict) else {}


def _json_safe_dict_list(value: object) -> list[dict[str, object]]:
    safe_value = json_safe_value(value)
    if not isinstance(safe_value, list):
        return []
    result: list[dict[str, object]] = []
    for item in safe_value:
        if isinstance(item, dict):
            result.append(dict(item))
    return result


def _workflow_duration_seconds(workflow: dict[str, Any]) -> float:
    started_at = workflow.get("started_at")
    if isinstance(started_at, datetime):
        started = started_at
    elif isinstance(started_at, str) and started_at.strip():
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            return 0.0
    else:
        return 0.0
    if started.tzinfo is None:
        started = timezone.make_aware(started, timezone.get_current_timezone())
    return float(max(0.0, (timezone.now() - started).total_seconds()))


def _existing_finalized_payload(job: ImportJob) -> dict[str, object]:
    existing_summary = dict(job.result_summary or {})
    return {
        "success": bool(existing_summary.get("success", False)),
        "created_count": int(existing_summary.get("created_count", 0) or 0),
        "updated_count": int(existing_summary.get("updated_count", 0) or 0),
        "skipped_count": int(existing_summary.get("skipped_count", 0) or 0),
        "error_count": int(existing_summary.get("error_count", 0) or 0),
        "review_count": int(existing_summary.get("review_count", 0) or 0),
        "review_overflow_count": int(existing_summary.get("review_overflow_count", 0) or 0),
        "review_total_count": int(existing_summary.get("review_total_count", 0) or 0),
        "follow_up": import_follow_up.normalize_follow_up_outcome(
            existing_summary.get("follow_up")
        ),
    }


def _rollup_load_phase(*, job: ImportJob) -> ImportLoadRollup:
    load_phases = list(
        ImportChunkPhase.objects.filter(
            chunk__job=job,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
        )
        .select_related("chunk")
        .order_by("chunk__chunk_role", "chunk__ordinal", "id")
    )

    result = ImportResult(success=True)
    load_outcome = ImportLoadOutcome()
    total_db_time = 0.0
    result_entity_counts: dict[str, int] = {}
    for phase in load_phases:
        metrics = dict(phase.metrics_payload or {})
        created_count = int(metrics.get("created_count", 0) or 0)
        result.created_count += created_count
        result.skipped_count += int(metrics.get("skipped_count", 0) or 0)
        result.error_count += int(metrics.get("error_count", 0) or 0)
        total_db_time += float(metrics.get("total_db_time", 0.0) or 0.0)
        chunk_entity_type = str(phase.chunk.entity_type or "").strip().lower()
        if chunk_entity_type:
            result_entity_counts[chunk_entity_type] = (
                result_entity_counts.get(chunk_entity_type, 0) + created_count
            )
        load_outcome.listing_wilaya_ids.update(
            int(value)
            for value in list(metrics.get("listing_wilaya_ids", []) or [])
            if int(value) > 0
        )
        load_outcome.demande_ids.update(
            int(value) for value in list(metrics.get("demande_ids", []) or []) if int(value) > 0
        )
        load_outcome.demande_client_ids.update(
            int(value)
            for value in list(metrics.get("demande_client_ids", []) or [])
            if int(value) > 0
        )
        load_outcome.offer_ids.update(
            int(value) for value in list(metrics.get("offer_ids", []) or []) if int(value) > 0
        )
        load_outcome.committed_entities.update(
            str(value)
            for value in list(metrics.get("committed_entities", []) or [])
            if str(value or "").strip()
        )
    return ImportLoadRollup(
        result=result,
        load_outcome=load_outcome,
        result_entity_counts=result_entity_counts,
        total_db_time=total_db_time,
        phase_count=len(load_phases),
    )


def _rollup_review_phase(
    *,
    job: ImportJob,
    review_rows: ReviewRows,
    phase_errors: list[dict[str, object]],
    prepare_counts: dict[str, object],
) -> ImportReviewRollup:
    safe_review_rows = _json_safe_dict_list(list(review_rows))
    safe_phase_errors = _json_safe_dict_list(phase_errors)
    review_overflow_total = review_overflow_count(review_rows)
    overflow_errors = _json_safe_dict_list(
        review_overflow_errors(overflow_count=review_overflow_total)
    )
    if overflow_errors:
        safe_phase_errors.extend(overflow_errors)

    if safe_review_rows:
        review_snapshot = persist_review_state_with_compatibility_sample(
            job=job,
            review_rows=cast(list[dict[str, Any]], safe_review_rows),
        )
    else:
        clear_db_review_state(job)
        review_snapshot = review_count_snapshot(job)

    visible_review_rows = _json_safe_dict_list(compatibility_review_rows(job))
    review_count = int(review_snapshot.visible_review_count or 0)
    review_total_count = review_count + review_overflow_total
    del prepare_counts
    return ImportReviewRollup(
        phase_errors=safe_phase_errors,
        review_snapshot=review_snapshot,
        visible_review_rows=visible_review_rows,
        review_count=review_count,
        review_overflow_total=review_overflow_total,
        review_total_count=review_total_count,
        has_review_rows=bool(safe_review_rows),
    )


def _decide_terminal_state(
    *,
    overflow_blocking: bool,
    cancel_requested: bool,
    has_review_rows: bool,
    rows_changed: bool,
    error_count: int,
) -> ImportTerminalDecision:
    if overflow_blocking:
        return ImportTerminalDecision(
            status=ImportJob.Status.FAILED,
            stage=ImportJob.Stage.REVIEW,
            final_phase="review",
            error_message=(
                "This import produced more unresolved review items than the system can safely process in one job."
            ),
            terminal_status="failed",
            job_completed_successfully=False,
        )
    if cancel_requested:
        return ImportTerminalDecision(
            status=ImportJob.Status.FAILED,
            stage=ImportJob.Stage.EXECUTION,
            final_phase="done",
            error_message="This import was cancelled before completion.",
            terminal_status="failed",
            job_completed_successfully=False,
        )
    if has_review_rows:
        return ImportTerminalDecision(
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            final_phase="review",
            error_message=None,
            terminal_status="review",
            job_completed_successfully=False,
        )
    if error_count > 0 and not rows_changed:
        return ImportTerminalDecision(
            status=ImportJob.Status.FAILED,
            stage=ImportJob.Stage.EXECUTION,
            final_phase="done",
            error_message="A few lines couldn't be imported safely.",
            terminal_status="failed",
            job_completed_successfully=False,
        )
    return ImportTerminalDecision(
        status=ImportJob.Status.COMPLETED,
        stage=ImportJob.Stage.EXECUTION,
        final_phase="done",
        error_message=None,
        terminal_status="completed",
        job_completed_successfully=True,
    )


def _update_terminal_result_summary(
    *,
    job: ImportJob,
    result: ImportResult,
    review_rollup: ImportReviewRollup,
    dead_letter_summary: dict[str, int],
    result_entity_counts: dict[str, int],
    overflow_blocking: bool,
    terminal_decision: ImportTerminalDecision,
) -> tuple[dict[str, object], dict[str, object]]:
    result_summary = dict(job.result_summary or {})
    result_summary.update(
        {
            "success": terminal_decision.job_completed_successfully,
            "created_count": result.created_count,
            "updated_count": 0,
            "skipped_count": result.skipped_count,
            "error_count": result.error_count,
            "errors": list(review_rollup.phase_errors),
            "review_count": review_rollup.review_count,
            "review_overflow_count": review_rollup.review_overflow_total,
            "review_total_count": review_rollup.review_total_count,
            "review_state": (
                "emergency_overflow"
                if overflow_blocking
                else ("normal" if review_rollup.review_count > 0 else "none")
            ),
            "overflow_blocking": overflow_blocking,
            "review_disabled": overflow_blocking,
            "review_disabled_reason": (
                "This import produced more unresolved review items than the system can safely process in one job."
                if overflow_blocking
                else ""
            ),
            "dead_letter_summary": dead_letter_summary,
            "result_entity_counts": result_entity_counts,
            "result_auto_fix_summary": dict(
                (job.inference_summary or {}).get("preview_auto_fix_summary", {}) or {}
            ),
            "review_storage_mode": "db_paged_v2",
        }
    )
    terminal_state = derive_terminal_result_state(
        status=terminal_decision.terminal_status,
        row_count=int((job.result_summary or {}).get("row_count", 0) or 0),
        created_count=int(result.created_count or 0),
        updated_count=0,
        skipped_count=int(result.skipped_count or 0),
        error_count=int(result.error_count or 0),
        review_total_count=review_rollup.review_total_count,
        overflow_blocking=overflow_blocking,
        explicit_terminal_reason=(
            "cancelled"
            if terminal_decision.error_message == "This import was cancelled before completion."
            else ""
        ),
    )
    result_summary.update(terminal_state)
    safe_summary = _json_safe_dict(result_summary)
    return safe_summary, _json_safe_dict(terminal_state)


def _terminal_notification_data(
    *,
    job: ImportJob,
    entity_type: str,
    result: ImportResult,
    review_rollup: ImportReviewRollup,
) -> dict[str, object]:
    return {
        "session_id": str(job.id),
        "entity_type": entity_type,
        "created": result.created_count,
        "updated": 0,
        "errors": result.error_count,
        "review": review_rollup.review_total_count,
        "review_overflow_count": review_rollup.review_overflow_total,
        "review_pending_group_count": int(review_rollup.review_snapshot.pending_group_count or 0),
    }


def _emit_terminal_notification(
    *,
    terminal_decision: ImportTerminalDecision,
    job: ImportJob,
    user_id: int,
    entity_type: str,
    result: ImportResult,
    review_rollup: ImportReviewRollup,
) -> None:
    if terminal_decision.error_message == (
        "This import produced more unresolved review items than the system can safely process in one job."
    ):
        emit_import_notification(
            event_type="import.execution_failed",
            user_id=user_id,
            title="Import failed",
            body=f"Your import for {job.filename} exceeded safe review capacity.",
            data=_terminal_notification_data(
                job=job,
                entity_type=entity_type,
                result=result,
                review_rollup=review_rollup,
            ),
        )
        return
    if terminal_decision.error_message == "This import was cancelled before completion.":
        emit_import_notification(
            event_type="import.execution_failed",
            user_id=user_id,
            title="Import cancelled",
            body=f"Your import for {job.filename} was cancelled before it could finish.",
            data=_terminal_notification_data(
                job=job,
                entity_type=entity_type,
                result=result,
                review_rollup=review_rollup,
            ),
        )
        return
    if terminal_decision.stage == ImportJob.Stage.REVIEW:
        emit_import_notification(
            event_type="import.review_required",
            user_id=user_id,
            title="Import needs review",
            body=f"Your import for {job.filename} needs review before it can finish.",
            data=_terminal_notification_data(
                job=job,
                entity_type=entity_type,
                result=result,
                review_rollup=review_rollup,
            ),
        )
        return
    if terminal_decision.status == ImportJob.Status.FAILED:
        emit_import_notification(
            event_type="import.execution_failed",
            user_id=user_id,
            title="Import failed",
            body=f"Your import for {job.filename} couldn't finish cleanly.",
            data=_terminal_notification_data(
                job=job,
                entity_type=entity_type,
                result=result,
                review_rollup=review_rollup,
            ),
        )


def _finalize_progress_detail(
    *,
    job: ImportJob,
    result: ImportResult,
    final_phase: str,
    bundle_mode: str,
    chunks_total: int,
    review_rollup: ImportReviewRollup,
    overflow_blocking: bool,
    result_summary: dict[str, object],
    terminal_state: dict[str, object],
) -> dict[str, object]:
    total_rows = int((job.result_summary or {}).get("row_count", 0) or 0)
    progress_detail = _json_safe_dict(
        build_progress_detail(
            rows_total=total_rows,
            rows_processed=total_rows,
            rows_created=result.created_count,
            rows_updated=0,
            rows_skipped=result.skipped_count,
            rows_review=review_rollup.review_total_count,
            current_chunk=max(1, chunks_total),
            chunks_total=max(1, chunks_total),
            phase=final_phase,
            bundle_mode=bundle_mode,
            review_overflow_count_value=review_rollup.review_overflow_total,
        )
    )
    progress_detail["review_pending_group_count"] = int(
        review_rollup.review_snapshot.pending_group_count or 0
    )
    progress_detail["review_state"] = str(result_summary.get("review_state", "none") or "none")
    progress_detail["overflow_blocking"] = overflow_blocking
    progress_detail["review_disabled"] = overflow_blocking
    progress_detail["review_disabled_reason"] = str(
        result_summary.get("review_disabled_reason", "") or ""
    )
    progress_detail.update(terminal_state)
    return progress_detail


def _save_finalized_job(
    *,
    job: ImportJob,
    workflow: dict[str, object],
    save_workflow_payload: Any,
    save_update_fields: list[str],
    user_id: int,
    entity_type: str,
    result: ImportResult,
    review_rollup: ImportReviewRollup,
) -> import_follow_up.SuccessNotificationStepOutcome:
    success_notification_step = import_follow_up.build_success_notification_step()
    workflow["status"] = str(job.status)
    if job.status != ImportJob.Status.COMPLETED:
        save_workflow_payload(job, workflow)
        job.save(update_fields=save_update_fields)
        return success_notification_step

    with transaction.atomic():
        success_notification_step = cast(
            import_follow_up.SuccessNotificationStepOutcome,
            record_import_success_notification(
                agency_id=int(getattr(job, "agency_id", 0) or 0),
                user_id=user_id,
                job_id=str(job.id),
                filename=str(job.filename or ""),
                entity_type=entity_type,
                created_count=int(result.created_count or 0),
                updated_count=0,
                error_count=int(result.error_count or 0),
                review_total_count=int(review_rollup.review_total_count or 0),
                review_overflow_count=int(review_rollup.review_overflow_total or 0),
                review_pending_group_count=int(
                    review_rollup.review_snapshot.pending_group_count or 0
                ),
            ),
        )
        save_workflow_payload(job, workflow)
        job.save(update_fields=save_update_fields)
    return success_notification_step


def finalize_distributed_import_job(
    *,
    job: ImportJob,
    user_id: int,
) -> dict[str, object]:
    from server.services.import_chunk_workflow import (
        collected_review_rows,
        save_workflow_payload,
        workflow_payload,
    )

    workflow = {str(key): value for key, value in workflow_payload(job).items()}
    if bool(workflow.get("finalized", False)):
        return _existing_finalized_payload(job)

    params = dict(workflow.get("params", {}) or {})
    cancel_requested = bool(workflow.get("cancel_requested", False))
    prepare_counts = dict(workflow.get("prepare_counts", {}) or {})
    dead_letter_summary = {
        str(key): int(value)
        for key, value in dict(prepare_counts.get("dead_letter_summary", {}) or {}).items()
        if isinstance(value, (int, float))
    }
    entity_type = str(params.get("entity_type", job.detected_entity or "") or "")

    load_rollup = _rollup_load_phase(job=job)
    result = load_rollup.result
    review_rows, phase_errors = collected_review_rows(job)
    try:
        review_rollup = _rollup_review_phase(
            job=job,
            review_rows=review_rows,
            phase_errors=phase_errors,
            prepare_counts=prepare_counts,
        )
        overflow_blocking = review_rollup.review_overflow_total > 0
        result.errors = list(review_rollup.phase_errors)
        result.error_count = max(
            result.error_count,
            len(review_rollup.phase_errors),
            int(prepare_counts.get("error_count", 0) or 0),
        )

        workflow["finalized"] = True
        workflow["finished_at"] = timezone.now().isoformat()
        rows_changed = int(result.created_count or 0) > 0
        terminal_decision = _decide_terminal_state(
            overflow_blocking=overflow_blocking,
            cancel_requested=cancel_requested,
            has_review_rows=review_rollup.has_review_rows,
            rows_changed=rows_changed,
            error_count=result.error_count,
        )

        result_summary, terminal_state = _update_terminal_result_summary(
            job=job,
            result=result,
            review_rollup=review_rollup,
            dead_letter_summary=dead_letter_summary,
            result_entity_counts=load_rollup.result_entity_counts,
            overflow_blocking=overflow_blocking,
            terminal_decision=terminal_decision,
        )
        job.review_rows = cast(list[dict[str, Any]], review_rollup.visible_review_rows)
        job.progress = 100
        job.status = terminal_decision.status
        job.stage = terminal_decision.stage
        job.error_message = terminal_decision.error_message
        job.result_summary = cast(dict[str, Any], result_summary)
        unchanged_count_value = terminal_state.get("unchanged_count", 0)
        result.unchanged_count = (
            int(unchanged_count_value)
            if isinstance(unchanged_count_value, (int, float, str))
            else 0
        )
        result.result_zero_change = bool(terminal_state.get("result_zero_change", False))
        zero_change_reasons_value = terminal_state.get("result_zero_change_reasons", [])
        result.result_zero_change_reasons = [
            str(value)
            for value in (
                list(zero_change_reasons_value)
                if isinstance(zero_change_reasons_value, list)
                else []
            )
            if str(value or "").strip()
        ]
        result.terminal_reason = str(terminal_state.get("terminal_reason") or "")
        topology = import_job_topology.job_topology(job)
        job.progress_detail = cast(
            dict[str, Any],
            _finalize_progress_detail(
                job=job,
                result=result,
                final_phase=terminal_decision.final_phase,
                bundle_mode=topology.bundle_mode,
                chunks_total=load_rollup.phase_count,
                review_rollup=review_rollup,
                overflow_blocking=overflow_blocking,
                result_summary=result_summary,
                terminal_state=terminal_state,
            ),
        )

        _emit_terminal_notification(
            terminal_decision=terminal_decision,
            job=job,
            user_id=user_id,
            entity_type=entity_type,
            result=result,
            review_rollup=review_rollup,
        )

        save_update_fields = [
            "result_summary",
            "review_rows",
            "progress",
            "status",
            "stage",
            "progress_detail",
            "error_message",
            "updated_at",
        ]
        success_notification_step = _save_finalized_job(
            job=job,
            workflow=workflow,
            save_workflow_payload=save_workflow_payload,
            save_update_fields=save_update_fields,
            user_id=user_id,
            entity_type=entity_type,
            result=result,
            review_rollup=review_rollup,
        )

        follow_up = import_follow_up.run_post_import_follow_up(
            job_id=str(job.id),
            entity_types=set(load_rollup.load_outcome.committed_entities),
            success_notification_step=success_notification_step,
            rebuild_handoff=lambda: import_rebuild_handoff.enqueue_post_import_rebuilds_for_entities(
                entity_types=set(load_rollup.load_outcome.committed_entities),
                agency_id=int(getattr(job, "agency_id", 0) or 0),
                listing_wilaya_ids=set(load_rollup.load_outcome.listing_wilaya_ids),
                demande_ids=set(load_rollup.load_outcome.demande_ids),
                demande_client_ids=set(load_rollup.load_outcome.demande_client_ids),
                offer_ids=set(load_rollup.load_outcome.offer_ids),
            ),
        )
        import_follow_up.persist_post_import_follow_up(
            job=job,
            outcome=follow_up,
            workflow=workflow,
            save_workflow_payload_fn=save_workflow_payload,
        )

        import_execution_metrics.record_import_metrics(
            entity_type=entity_type or str(job.detected_entity or ""),
            result=result,
            review_count=review_rollup.review_total_count,
            execution_started_at=time.monotonic(),
            total_db_time=load_rollup.total_db_time,
            duration_s=_workflow_duration_seconds(workflow),
        )
        return {
            "success": terminal_decision.job_completed_successfully,
            "created_count": result.created_count,
            "updated_count": 0,
            "skipped_count": result.skipped_count,
            "error_count": result.error_count,
            "review_count": review_rollup.review_count,
            "review_overflow_count": review_rollup.review_overflow_total,
            "review_total_count": review_rollup.review_total_count,
            "follow_up": import_follow_up.normalize_follow_up_outcome(
                (job.result_summary or {}).get("follow_up")
            ),
        }
    finally:
        cleanup_review_rows = getattr(review_rows, "cleanup", None)
        if callable(cleanup_review_rows):
            cleanup_review_rows()


__all__ = ["finalize_distributed_import_job"]
