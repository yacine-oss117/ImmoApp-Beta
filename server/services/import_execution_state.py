"""Execution state and failure helpers for direct importer flows."""

from __future__ import annotations

import logging
import math
import shutil
from typing import Any, cast

from django.db import transaction

from server.imports.models import ImportJob
from server.services.duplicate_checker import DuplicateCheckUnavailableError
from server.services.import_follow_up import merge_follow_up_outcomes
from server.services.import_load_service import ImportLoadConsistencyError
from server.services.import_notifications import record_import_success_notification
from server.services.import_progress_runtime import build_progress_detail
from server.services.import_review_runtime import review_overflow_count
from server.services.import_review_runtime_state import persist_review_state
from server.services.import_review_store import clear_db_review_state, review_count_snapshot
from server.services.import_status_resolver import resolve_import_status
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRowBuffer
from server.services.import_ui_summary import derive_terminal_result_state
from server.services.json_safe import json_safe_value
from server.services.storage import StorageError

logger = logging.getLogger(__name__)


def friendly_import_error_message(exc: Exception) -> str:
    if isinstance(exc, StorageError):
        return "We couldn't read this file yet. Please try again or choose another file."
    if isinstance(exc, ImportLoadConsistencyError):
        return str(exc)
    if isinstance(exc, DuplicateCheckUnavailableError):
        return "We couldn't verify duplicates right now. Please retry this import."
    return "We couldn't finish this import yet. Please try again."


def cleanup_prepared_artifact(artifact: PreparedImportArtifact | None) -> None:
    if artifact is None:
        return
    if artifact.temp_path:
        try:
            artifact.temp_path.unlink()
        except OSError:
            pass
    if artifact.spool_dir:
        try:
            shutil.rmtree(artifact.spool_dir, ignore_errors=True)
        except OSError:
            pass


def review_progress_detail(
    *,
    artifact: PreparedImportArtifact,
    result: ImportResult,
    review_rows: ReviewRowBuffer,
) -> dict[str, object]:
    return build_progress_detail(
        rows_total=artifact.total_rows,
        rows_processed=artifact.total_rows,
        rows_created=result.created_count,
        rows_updated=result.updated_count,
        rows_skipped=result.skipped_count,
        rows_review=len(review_rows),
        current_chunk=max(0, math.ceil(result.created_count / max(1, artifact.current_batch_size))),
        chunks_total=artifact.chunks_total,
        phase="review" if review_rows else "executing",
        bundle_mode=artifact.bundle_mode,
        review_overflow_count_value=review_overflow_count(review_rows),
    )


def persist_direct_execution_state(
    *,
    job: ImportJob,
    user_id: int,
    artifact: PreparedImportArtifact,
    result: ImportResult,
    review_rows: ReviewRowBuffer,
) -> None:
    overflow_count = review_overflow_count(review_rows)
    overflow_blocking = overflow_count > 0
    row_count = int(artifact.total_rows or 0)
    rows_changed = int(result.created_count or 0) > 0 or int(result.updated_count or 0) > 0
    progress_detail = review_progress_detail(
        artifact=artifact,
        result=result,
        review_rows=review_rows,
    )
    direct_result_entity_counts = {
        str(key): int(value)
        for key, value in dict(result.created_entity_counts or {}).items()
        if isinstance(value, (int, float))
    }
    if review_rows:
        persist_review_state(
            job=job,
            review_rows=review_rows,
            progress_detail=progress_detail,
        )
        snapshot = review_count_snapshot(job)
        result_summary = dict(job.result_summary or {})
        result_summary["success"] = False
        result_summary["created_count"] = int(result.created_count or 0)
        result_summary["updated_count"] = int(result.updated_count or 0)
        result_summary["skipped_count"] = int(result.skipped_count or 0)
        result_summary["error_count"] = int(result.error_count or 0)
        result_summary["errors"] = cast(list[dict[str, Any]], json_safe_value(list(result.errors)))
        result_summary["review_count"] = int(snapshot.visible_review_count or 0)
        result_summary["review_overflow_count"] = overflow_count
        result_summary["review_total_count"] = (
            int(snapshot.visible_review_count or 0) + overflow_count
        )
        result_summary["review_pending_group_count"] = int(snapshot.pending_group_count or 0)
        result_summary["result_entity_counts"] = direct_result_entity_counts
        result_summary["review_storage_mode"] = "db_paged_v2"
        terminal_state = derive_terminal_result_state(
            status="failed" if overflow_blocking else "review",
            row_count=row_count,
            created_count=int(result.created_count or 0),
            updated_count=int(result.updated_count or 0),
            skipped_count=int(result.skipped_count or 0),
            error_count=int(result.error_count or 0),
            review_total_count=int(result_summary["review_total_count"] or 0),
            overflow_blocking=overflow_blocking,
        )
        result_summary.update(terminal_state)
        job.result_summary = result_summary
        progress_payload = dict(job.progress_detail or {})
        progress_payload["rows_created"] = int(result.created_count or 0)
        progress_payload["rows_updated"] = int(result.updated_count or 0)
        progress_payload["rows_skipped"] = int(result.skipped_count or 0)
        progress_payload["rows_review"] = int(snapshot.visible_review_count or 0) + overflow_count
        progress_payload["error_count"] = int(result.error_count or 0)
        progress_payload["review_overflow_count"] = overflow_count
        progress_payload["review_pending_group_count"] = int(snapshot.pending_group_count or 0)
        progress_payload.update(terminal_state)
        progress_payload["review_state"] = "emergency_overflow" if overflow_blocking else "normal"
        resolved_status = resolve_import_status(
            session_status=ImportJob.Status.FAILED if overflow_blocking else ImportJob.Status.READY,
            session_stage=ImportJob.Stage.REVIEW,
            progress=int(job.progress or 0),
            progress_detail=progress_payload,
            result_summary=result_summary,
            review_visible_count=int(snapshot.visible_review_count or 0),
        )
        result_summary["overflow_blocking"] = resolved_status.overflow_blocking
        result_summary["review_disabled"] = resolved_status.review_disabled
        result_summary["review_disabled_reason"] = resolved_status.review_disabled_reason
        if overflow_blocking:
            result_summary["review_state"] = "emergency_overflow"
            progress_payload["review_state"] = "emergency_overflow"
        progress_payload["overflow_blocking"] = resolved_status.overflow_blocking
        progress_payload["review_disabled"] = resolved_status.review_disabled
        progress_payload["review_disabled_reason"] = resolved_status.review_disabled_reason
        job.progress_detail = progress_payload
        unchanged_count_value = terminal_state.get("unchanged_count", 0)
        result.unchanged_count = (
            int(unchanged_count_value)
            if isinstance(unchanged_count_value, (int, float, str, bytes, bytearray))
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
        job.result_summary = result_summary
        if overflow_blocking:
            result.success = False
            job.error_message = resolved_status.review_disabled_reason
        else:
            job.error_message = None
        job.status = resolved_status.job_status
        job.stage = resolved_status.job_stage
        job.save(
            update_fields=[
                "result_summary",
                "progress_detail",
                "status",
                "stage",
                "error_message",
                "updated_at",
            ]
        )
        return

    clear_db_review_state(job)
    job.review_rows = []
    progress_detail["review_overflow_count"] = overflow_count
    progress_detail["review_pending_group_count"] = 0
    progress_detail["review_state"] = "emergency_overflow" if overflow_blocking else "none"
    progress_detail["overflow_blocking"] = overflow_blocking
    progress_detail["review_disabled"] = overflow_blocking
    progress_detail["review_disabled_reason"] = (
        "This import produced more unresolved review items than the system can safely process in one job."
        if overflow_blocking
        else ""
    )
    progress_detail["error_count"] = int(result.error_count or 0)
    progress_detail["phase"] = "done"
    job.progress_detail = dict(progress_detail)
    result_summary = dict(job.result_summary or {})
    direct_success = bool(
        result.success
        and not overflow_blocking
        and (rows_changed or int(result.error_count or 0) <= 0)
    )
    result_summary["success"] = direct_success
    result_summary["created_count"] = int(result.created_count or 0)
    result_summary["updated_count"] = int(result.updated_count or 0)
    result_summary["skipped_count"] = int(result.skipped_count or 0)
    result_summary["error_count"] = int(result.error_count or 0)
    result_summary["errors"] = cast(list[dict[str, Any]], json_safe_value(list(result.errors)))
    result_summary["result_entity_counts"] = direct_result_entity_counts
    result_summary["review_count"] = 0
    result_summary["review_overflow_count"] = overflow_count
    result_summary["review_total_count"] = overflow_count
    result_summary["review_storage_mode"] = "db_paged_v2"
    result_summary["review_pending_group_count"] = 0
    result_summary["review_state"] = str(progress_detail.get("review_state", "none") or "none")
    status_hint = (
        "failed"
        if overflow_blocking
        or ((int(result.error_count or 0) > 0 or not result.success) and not rows_changed)
        else "completed"
    )
    terminal_state = derive_terminal_result_state(
        status=status_hint,
        row_count=row_count,
        created_count=int(result.created_count or 0),
        updated_count=int(result.updated_count or 0),
        skipped_count=int(result.skipped_count or 0),
        error_count=int(result.error_count or 0),
        review_total_count=int(result_summary["review_total_count"] or 0),
        overflow_blocking=overflow_blocking,
    )
    result_summary.update(terminal_state)
    resolved_status = resolve_import_status(
        session_status=(
            ImportJob.Status.FAILED if status_hint == "failed" else ImportJob.Status.COMPLETED
        ),
        session_stage=ImportJob.Stage.REVIEW if overflow_blocking else ImportJob.Stage.EXECUTION,
        progress=100,
        progress_detail=progress_detail,
        result_summary=result_summary,
        review_visible_count=0,
    )
    result_summary["overflow_blocking"] = resolved_status.overflow_blocking
    result_summary["review_disabled"] = resolved_status.review_disabled
    result_summary["review_disabled_reason"] = resolved_status.review_disabled_reason
    job.result_summary = result_summary
    progress_detail.update(terminal_state)
    progress_detail["overflow_blocking"] = resolved_status.overflow_blocking
    progress_detail["review_disabled"] = resolved_status.review_disabled
    progress_detail["review_disabled_reason"] = resolved_status.review_disabled_reason
    job.progress_detail = dict(progress_detail)
    unchanged_count_value = terminal_state.get("unchanged_count", 0)
    result.unchanged_count = (
        int(unchanged_count_value)
        if isinstance(unchanged_count_value, (int, float, str, bytes, bytearray))
        else 0
    )
    result.result_zero_change = bool(terminal_state.get("result_zero_change", False))
    zero_change_reasons_value = terminal_state.get("result_zero_change_reasons", [])
    result.result_zero_change_reasons = [
        str(value)
        for value in (
            list(zero_change_reasons_value) if isinstance(zero_change_reasons_value, list) else []
        )
        if str(value or "").strip()
    ]
    result.terminal_reason = str(terminal_state.get("terminal_reason") or "")
    job.stage = resolved_status.job_stage
    update_fields = ["review_rows", "result_summary", "progress_detail", "stage", "updated_at"]
    if overflow_blocking:
        result.success = False
        job.status = resolved_status.job_status
        job.progress = 100
        job.error_message = resolved_status.review_disabled_reason
        update_fields.extend(["status", "progress", "error_message"])
    elif (int(result.error_count or 0) > 0 or not result.success) and not rows_changed:
        result.success = False
        job.status = resolved_status.job_status
        job.progress = 100
        job.error_message = "A few lines couldn't be imported safely."
        update_fields.extend(["status", "progress", "error_message"])
    else:
        result.success = True
        with transaction.atomic():
            fresh_follow_up = result_summary.get("follow_up")
            if (
                isinstance(job, ImportJob)
                and getattr(job, "pk", None)
                and hasattr(job, "refresh_from_db")
            ):
                try:
                    job.refresh_from_db(fields=["result_summary"])
                except Exception:
                    pass
                else:
                    persisted_summary = dict(job.result_summary or {})
                    fresh_follow_up = persisted_summary.get("follow_up", fresh_follow_up)
            success_notification_step = record_import_success_notification(
                agency_id=int(getattr(job, "agency_id", 0) or 0),
                user_id=int(user_id),
                job_id=str(job.id),
                filename=str(job.filename or ""),
                entity_type=str(job.detected_entity or artifact.entity_type or ""),
                created_count=int(result.created_count or 0),
                updated_count=int(result.updated_count or 0),
                error_count=int(result.error_count or 0),
                review_total_count=int(result_summary.get("review_total_count", 0) or 0),
                review_overflow_count=int(result_summary.get("review_overflow_count", 0) or 0),
                review_pending_group_count=int(
                    result_summary.get("review_pending_group_count", 0) or 0
                ),
            )
            merged_follow_up = merge_follow_up_outcomes(
                fresh_follow_up,
                {
                    "entities": sorted(direct_result_entity_counts),
                    "steps": {
                        "success_notification": success_notification_step,
                    },
                },
            )
            result_summary["follow_up"] = cast(dict[str, Any], json_safe_value(merged_follow_up))
            job.result_summary = result_summary
            job.status = resolved_status.job_status
            job.progress = 100
            job.error_message = None
            update_fields.extend(["status", "progress", "error_message"])
            job.save(update_fields=update_fields)
        return
    job.save(update_fields=update_fields)


def mark_job_failed(job: ImportJob, exc: Exception) -> None:
    logger.exception("Import execution failed")
    clear_db_review_state(job)
    job.review_rows = []
    result_summary = dict(job.result_summary or {})
    result_summary["review_count"] = 0
    result_summary["review_overflow_count"] = 0
    result_summary["review_total_count"] = 0
    result_summary["review_pending_group_count"] = 0
    result_summary["review_state"] = "none"
    terminal_state = derive_terminal_result_state(
        status="failed",
        row_count=int(result_summary.get("row_count", 0) or 0),
        created_count=int(result_summary.get("created_count", 0) or 0),
        updated_count=int(result_summary.get("updated_count", 0) or 0),
        skipped_count=int(result_summary.get("skipped_count", 0) or 0),
        error_count=max(1, int(result_summary.get("error_count", 0) or 0)),
        review_total_count=0,
        overflow_blocking=False,
    )
    result_summary.update(terminal_state)
    resolved_status = resolve_import_status(
        session_status=ImportJob.Status.FAILED,
        session_stage=ImportJob.Stage.EXECUTION,
        progress=100,
        progress_detail=job.progress_detail or {},
        result_summary=result_summary,
        review_visible_count=0,
    )
    result_summary["overflow_blocking"] = resolved_status.overflow_blocking
    result_summary["review_disabled"] = resolved_status.review_disabled
    result_summary["review_disabled_reason"] = resolved_status.review_disabled_reason
    job.result_summary = result_summary
    progress_detail = dict(job.progress_detail or {})
    progress_detail["review_overflow_count"] = 0
    progress_detail["review_pending_group_count"] = 0
    progress_detail["review_state"] = "none"
    progress_detail.update(terminal_state)
    progress_detail["overflow_blocking"] = resolved_status.overflow_blocking
    progress_detail["review_disabled"] = resolved_status.review_disabled
    progress_detail["review_disabled_reason"] = resolved_status.review_disabled_reason
    job.progress_detail = progress_detail
    job.stage = resolved_status.job_stage
    job.status = resolved_status.job_status
    job.progress = 100
    job.error_message = friendly_import_error_message(exc)
    job.save(
        update_fields=[
            "review_rows",
            "result_summary",
            "progress_detail",
            "stage",
            "status",
            "progress",
            "error_message",
            "updated_at",
        ]
    )


__all__ = [
    "cleanup_prepared_artifact",
    "friendly_import_error_message",
    "mark_job_failed",
    "persist_direct_execution_state",
    "review_progress_detail",
]
