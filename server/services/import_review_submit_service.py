"""Orchestration helpers for async importer review submission."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

from django.db import transaction

from core.importer.normalize_pipeline import NormalizationPipeline
from server.imports.models import ImportJob, ImportReviewItem
from server.services.import_review_conflicts import (
    RowConflict,
    conflict_detail,
    detect_create_conflicts,
)
from server.services.import_review_finalize_service import finalize_review_submission
from server.services.import_review_payloads import (
    NormalizedReviewSubmitRequest,
    PreparedReviewSubmitPayload,
    build_review_duplicate_conflict_response,
    build_review_submit_accepted_response,
    merge_review_submit_payloads,
    prepare_effective_review_submit_payload,
)
from server.services.import_review_queries import (
    active_review_items,
    pending_item_rows,
    review_count_snapshot,
    row_to_item_id_map,
)
from server.services.import_review_resolution_errors import ImportReviewConflictError
from server.services.import_review_row_actions import (
    collect_review_actions,
    normalize_resolution_inputs,
)
from server.services.import_review_shapes import review_row_key
from server.services.import_review_store import (
    apply_group_resolution_templates,
    apply_item_resolutions,
    build_effective_submit_payload,
    ensure_review_state,
)
from server.services.import_review_submit_attempts import (
    StaleImportTaskAttemptError,
    assert_review_submit_attempt_current,
    run_review_submit_terminal_section,
    run_with_review_submit_attempt_fence,
)
from server.services.import_review_submit_dispatch import (
    REVIEW_SUBMIT_DISPATCH_COMPLETED,
    REVIEW_SUBMIT_DISPATCH_CONFLICT,
    REVIEW_SUBMIT_DISPATCH_FAILED,
    REVIEW_SUBMIT_WORKFLOW_KEY,
    begin_review_submit_dispatch,
    claim_review_submit_dispatch_start,
    generate_review_submit_task_id,
    load_review_submit_workflow,
    persist_review_submit_workflow,
    publish_review_submit_dispatch,
)
from server.services.import_review_submit_recovery import (
    persist_review_submit_conflict_terminal,
    persist_review_submit_failure_terminal,
    persist_review_submit_ready_state,
    review_submit_generic_error_payload,
)
from server.services.import_rows import validate_row
from server.services.import_types import ReviewResolutionPayload, ReviewRowPayload
from server.services.json_safe import json_safe_value

_REVIEW_SUBMIT_POLL_AFTER_MS = 150

logger = logging.getLogger(__name__)


class ImportReviewSubmitConflictError(RuntimeError):
    def __init__(
        self,
        *,
        detail: str,
        row_conflicts: list[RowConflict],
        conflict_groups: list[str],
        conflict_item_ids: list[int],
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.row_conflicts = list(row_conflicts)
        self.conflict_groups = sorted(set(conflict_groups))
        self.conflict_item_ids = sorted(set(conflict_item_ids))


def _coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip() or "0")
        except ValueError:
            return default
    return default


def _dict(value: object) -> dict[str, object]:
    return (
        {str(key): item for key, item in dict(value).items()} if isinstance(value, Mapping) else {}
    )


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _pending_group_lookup(items: list[ImportReviewItem]) -> dict[int, str]:
    return {int(item.id): str(item.group.group_key or "") for item in items}


def _map_conflicts_to_groups(
    *,
    row_conflicts: list[RowConflict],
    row_to_item: Mapping[str, int],
    item_to_group: Mapping[int, str],
) -> tuple[list[str], list[int]]:
    from server.services.import_review_shapes import review_row_key

    conflict_groups: list[str] = []
    conflict_item_ids: list[int] = []
    for conflict in row_conflicts:
        row_key = review_row_key(
            row_num=int(conflict.get("row", 0) or 0),
            entity_type=str(conflict.get("entity_type", "") or ""),
        )
        fallback_key = str(int(conflict.get("row", 0) or 0))
        item_id = int(row_to_item.get(row_key) or row_to_item.get(fallback_key, 0) or 0)
        if item_id <= 0:
            continue
        conflict_item_ids.append(item_id)
        group_key = str(item_to_group.get(item_id, "") or "")
        if group_key:
            conflict_groups.append(group_key)
    return conflict_groups, conflict_item_ids


def _build_prepared_submit(
    *,
    job: ImportJob,
    request_payload: NormalizedReviewSubmitRequest,
) -> tuple[
    PreparedReviewSubmitPayload,
    list[ImportReviewItem],
    dict[str, int],
    dict[int, str],
]:
    submit_items = active_review_items(job, include_item_resolutions=True)
    stored_corrections, stored_decisions, stored_skip_rows = build_effective_submit_payload(
        job,
        active_items=submit_items,
    )
    merged_request = merge_review_submit_payloads(
        request_payload=request_payload,
        stored_corrections=stored_corrections,
        stored_decisions=stored_decisions,
        stored_skip_rows=stored_skip_rows,
    )
    row_to_item = row_to_item_id_map(job, active_items=submit_items)
    item_to_group = _pending_group_lookup(submit_items)
    prepared_submit = prepare_effective_review_submit_payload(
        pending_rows=pending_item_rows(job, active_items=submit_items),
        corrections=merged_request.corrections,
        decisions=merged_request.decisions,
        skip_rows=merged_request.skip_rows,
        bulk_operations=merged_request.bulk_operations,
    )
    item_level_corrections = {
        review_row_key(
            row_num=int(item.row_ordinal or 0),
            entity_type=str(item.entity_type or ""),
        ): dict(correction_payload)
        for item in submit_items
        if (
            correction_payload := dict(
                cast(
                    Mapping[str, object],
                    dict(request_payload.item_decisions.get(str(item.id), {}) or {}).get(
                        "corrections",
                        {},
                    ),
                )
            )
        )
    }
    if item_level_corrections:
        merged_corrections = dict(prepared_submit.corrections)
        merged_corrections.update(item_level_corrections)
        prepared_submit = PreparedReviewSubmitPayload(
            corrections=merged_corrections,
            decisions=dict(prepared_submit.decisions),
            skip_rows=list(prepared_submit.skip_rows),
            pending_rows=list(prepared_submit.pending_rows),
        )
    return prepared_submit, submit_items, row_to_item, item_to_group


def _review_submit_task_response(job: ImportJob) -> dict[str, object]:
    return {
        "session_id": str(job.id),
        "status": str(job.status),
        "stage": str(job.stage),
        "task_id": str(job.task_id or ""),
    }


def kickoff_review_submission(
    *,
    job: ImportJob,
    actor_user_id: int,
    agency_id: int,
    entity_type: str,
    request_payload: NormalizedReviewSubmitRequest,
    enqueue_review_submit_task_fn: Callable[..., Any],
    register_task_fn: Callable[..., object],
    schema: str | None,
    correlation_id: str | None,
) -> dict[str, object]:
    task_id = generate_review_submit_task_id()

    with transaction.atomic():
        apply_group_resolution_templates(
            job=job,
            group_decisions=request_payload.group_decisions,
        )
        apply_item_resolutions(
            job=job,
            item_decisions=request_payload.item_decisions,
            skip_item_ids=request_payload.skip_item_ids,
        )
        prepared_submit, _submit_items, row_to_item, item_to_group = _build_prepared_submit(
            job=job,
            request_payload=request_payload,
        )
        prepared_rows = cast(list[ReviewRowPayload], prepared_submit.pending_rows)
        prepared_corrections = cast(Mapping[str, Mapping[str, object]], prepared_submit.corrections)
        prepared_decisions = cast(Mapping[str, Mapping[str, object]], prepared_submit.decisions)
        prepared_skip_rows = cast(list[int | str], list(prepared_submit.skip_rows))
        inputs = normalize_resolution_inputs(
            corrections=prepared_corrections,
            decisions=prepared_decisions,
            skip_rows=prepared_skip_rows,
            review_rows=prepared_rows,
            job_id=str(job.id),
            agency_id=agency_id,
        )
        state = collect_review_actions(
            job_id=str(job.id),
            agency_id=agency_id,
            user_id=actor_user_id,
            entity_type=entity_type,
            review_rows=prepared_rows,
            inputs=inputs,
            normalization_pipeline_cls=NormalizationPipeline,
            validate_row_fn=validate_row,
        )
        row_conflicts: list[RowConflict] = []
        for create_entity_type, pending_rows in state.create_pending_by_entity.items():
            row_conflicts.extend(
                detect_create_conflicts(
                    entity_type=create_entity_type,
                    agency_id=agency_id,
                    pending_rows=pending_rows,
                )
            )
        if row_conflicts:
            conflict_groups, conflict_item_ids = _map_conflicts_to_groups(
                row_conflicts=row_conflicts,
                row_to_item=row_to_item,
                item_to_group=item_to_group,
            )
            raise ImportReviewSubmitConflictError(
                detail=conflict_detail(row_conflicts),
                row_conflicts=row_conflicts,
                conflict_groups=conflict_groups,
                conflict_item_ids=conflict_item_ids,
            )

        persist_review_submit_workflow(
            job=job,
            request_payload=request_payload,
            prepared_submit=prepared_submit,
        )
        begin_review_submit_dispatch(
            job=job,
            task_id=task_id,
            actor_user_id=actor_user_id,
            agency_id=agency_id,
            schema=schema,
            correlation_id=correlation_id,
        )
        summary = _dict(job.result_summary)
        summary.pop("review_submit_conflict", None)
        summary.pop("review_submit_error", None)
        job.result_summary = cast(dict[str, object], json_safe_value(summary))
        job.task_id = task_id
        job.status = ImportJob.Status.RUNNING
        job.stage = ImportJob.Stage.REVIEW
        job.error_message = None
        job.progress_detail = cast(
            dict[str, object],
            json_safe_value(
                {
                    **_dict(job.progress_detail),
                    "phase": "review_submit",
                    "error_count": _coerce_int(summary.get("error_count", 0)),
                }
            ),
        )
        job.save(
            update_fields=[
                "task_id",
                "status",
                "stage",
                "error_message",
                "progress_detail",
                "result_summary",
                "updated_at",
            ]
        )
        transaction.on_commit(
            lambda: publish_review_submit_dispatch(
                job=job,
                enqueue_review_submit_task_fn=enqueue_review_submit_task_fn,
                register_task_fn=register_task_fn,
            )
        )

    snapshot = ensure_review_state(job) or review_count_snapshot(job)
    return build_review_submit_accepted_response(
        job=job,
        task_id=task_id,
        snapshot=snapshot,
        poll_after_ms=_REVIEW_SUBMIT_POLL_AFTER_MS,
    )


def run_review_submit_task(
    *,
    session_id: str,
    actor_user_id: int,
    agency_id: int,
    correlation_id: str | None,
    task_id: str | None = None,
) -> dict[str, object]:
    from server.services.import_review_execution_service import apply_review_resolutions

    job, claim_status = claim_review_submit_dispatch_start(
        session_id=session_id,
        agency_id=agency_id,
        task_id=task_id,
    )
    if job is None:
        return {"session_id": session_id, "status": "missing"}
    if claim_status != "started":
        return {"session_id": str(job.id), "status": claim_status}

    review_submit_payload = load_review_submit_workflow(job)
    if not review_submit_payload:
        logger.error(
            "Review-submit task started without persisted workflow payload",
            extra={
                "job_id": str(job.id),
                "agency_id": int(agency_id),
                "actor_user_id": int(actor_user_id),
                "correlation_id": str(correlation_id or ""),
                "task_id": str(task_id or ""),
            },
        )
        try:
            run_with_review_submit_attempt_fence(
                job=job,
                task_id=task_id,
                operation="review_submit_missing_workflow",
                fn=lambda locked_job: persist_review_submit_failure_terminal(
                    job=locked_job,
                    task_id=task_id,
                    clear_submit_payload=False,
                ),
            )
        except StaleImportTaskAttemptError as stale_exc:
            return {"session_id": str(job.id), "status": stale_exc.status}
        job.refresh_from_db()
        return _review_submit_task_response(job)
    corrections = {
        str(key): dict(value or {})
        for key, value in _dict(review_submit_payload.get("corrections")).items()
        if isinstance(value, Mapping)
    }
    decisions = {
        str(key): dict(value or {})
        for key, value in _dict(review_submit_payload.get("decisions")).items()
        if isinstance(value, Mapping)
    }
    skip_rows = [
        str(value)
        for value in _sequence(review_submit_payload.get("skip_rows", []))
        if str(value or "").strip()
    ]
    bulk_operations = [
        dict(value)
        for value in _sequence(review_submit_payload.get("bulk_operations", []))
        if isinstance(value, Mapping)
    ]
    try:
        assert_review_submit_attempt_current(job=job, task_id=task_id)
        prepared_submit, submit_items, row_to_item, item_to_group = _build_prepared_submit(
            job=job,
            request_payload=NormalizedReviewSubmitRequest(
                corrections=corrections,
                decisions=cast(dict[str, ReviewResolutionPayload], decisions),
                item_decisions={},
                group_decisions={},
                skip_rows=skip_rows,
                skip_item_ids=[],
                bulk_operations=bulk_operations,
            ),
        )
        prepared_rows = cast(list[ReviewRowPayload], prepared_submit.pending_rows)
        prepared_corrections = cast(Mapping[str, Mapping[str, object]], prepared_submit.corrections)
        prepared_decisions = cast(Mapping[str, Mapping[str, object]], prepared_submit.decisions)
        prepared_skip_rows = cast(list[int | str], list(prepared_submit.skip_rows))
        _ = submit_items

        def _terminal_success(
            locked_job: ImportJob,
            _finish_attempt: Callable[[str, Iterable[str]], dict[str, object]],
        ) -> dict[str, object]:
            review_result = apply_review_resolutions(
                job_id=str(locked_job.id),
                entity_type=str(locked_job.detected_entity or ""),
                review_rows=prepared_rows,
                corrections=prepared_corrections,
                decisions=prepared_decisions,
                skip_rows=prepared_skip_rows,
                user_id=actor_user_id,
                agency_id=agency_id,
            )
            finalize_review_submission(
                job=locked_job,
                actor_user_id=actor_user_id,
                review_result=review_result,
            )
            return _review_submit_task_response(locked_job)

        def _terminal_failure(
            locked_job: ImportJob,
            exc: Exception,
            finish_attempt: Callable[[str, Iterable[str]], dict[str, object]],
        ) -> dict[str, object]:
            if isinstance(exc, ImportReviewConflictError):
                conflict_groups, conflict_item_ids = _map_conflicts_to_groups(
                    row_conflicts=exc.row_conflicts,
                    row_to_item=row_to_item,
                    item_to_group=item_to_group,
                )
                snapshot = ensure_review_state(locked_job) or review_count_snapshot(locked_job)
                conflict_payload = build_review_duplicate_conflict_response(
                    job=locked_job,
                    detail=exc.detail,
                    row_conflicts=exc.row_conflicts,
                    conflict_groups=conflict_groups,
                    conflict_item_ids=conflict_item_ids,
                    correlation_id=str(correlation_id or ""),
                    snapshot=snapshot,
                    review_state=(
                        "normal" if int(snapshot.visible_review_count or 0) > 0 else "none"
                    ),
                )
                persist_review_submit_ready_state(job=locked_job, conflict_payload=conflict_payload)
                finish_attempt(REVIEW_SUBMIT_DISPATCH_CONFLICT, [REVIEW_SUBMIT_WORKFLOW_KEY])
                return _review_submit_task_response(locked_job)
            logger.exception(
                "Unexpected review-submit task failure",
                extra={
                    "job_id": str(locked_job.id),
                    "agency_id": int(agency_id),
                    "actor_user_id": int(actor_user_id),
                    "correlation_id": str(correlation_id or ""),
                    "task_id": str(task_id or ""),
                },
            )
            persist_review_submit_ready_state(
                job=locked_job,
                error_payload=review_submit_generic_error_payload(),
            )
            finish_attempt(REVIEW_SUBMIT_DISPATCH_FAILED, [REVIEW_SUBMIT_WORKFLOW_KEY])
            return _review_submit_task_response(locked_job)

        result_payload = run_review_submit_terminal_section(
            job=job,
            task_id=task_id,
            operation="review_submit_apply_finalize",
            success_status=REVIEW_SUBMIT_DISPATCH_COMPLETED,
            clear_workflow_keys=[REVIEW_SUBMIT_WORKFLOW_KEY],
            fn=_terminal_success,
            handle_exception=_terminal_failure,
        )
        return result_payload
    except StaleImportTaskAttemptError as exc:
        return {"session_id": str(job.id), "status": exc.status}
    except ImportReviewConflictError as exc:
        conflict_groups, conflict_item_ids = _map_conflicts_to_groups(
            row_conflicts=exc.row_conflicts,
            row_to_item=row_to_item,
            item_to_group=item_to_group,
        )
        snapshot = ensure_review_state(job) or review_count_snapshot(job)
        conflict_payload = build_review_duplicate_conflict_response(
            job=job,
            detail=exc.detail,
            row_conflicts=exc.row_conflicts,
            conflict_groups=conflict_groups,
            conflict_item_ids=conflict_item_ids,
            correlation_id=str(correlation_id or ""),
            snapshot=snapshot,
            review_state="normal" if int(snapshot.visible_review_count or 0) > 0 else "none",
        )
        try:
            run_with_review_submit_attempt_fence(
                job=job,
                task_id=task_id,
                operation="review_submit_conflict_recovery",
                fn=lambda locked_job: persist_review_submit_conflict_terminal(
                    job=locked_job,
                    task_id=task_id,
                    conflict_payload=conflict_payload,
                ),
            )
        except StaleImportTaskAttemptError as stale_exc:
            return {"session_id": str(job.id), "status": stale_exc.status}
        job.refresh_from_db()
        return _review_submit_task_response(job)
    except Exception:
        logger.exception(
            "Unexpected review-submit task failure",
            extra={
                "job_id": str(job.id),
                "agency_id": int(agency_id),
                "actor_user_id": int(actor_user_id),
                "correlation_id": str(correlation_id or ""),
                "task_id": str(task_id or ""),
            },
        )
        try:
            run_with_review_submit_attempt_fence(
                job=job,
                task_id=task_id,
                operation="review_submit_failure_recovery",
                fn=lambda locked_job: persist_review_submit_failure_terminal(
                    job=locked_job,
                    task_id=task_id,
                    clear_submit_payload=True,
                ),
            )
        except StaleImportTaskAttemptError as stale_exc:
            return {"session_id": str(job.id), "status": stale_exc.status}
        job.refresh_from_db()
        return _review_submit_task_response(job)


__all__ = [
    "ImportReviewSubmitConflictError",
    "kickoff_review_submission",
    "persist_review_submit_ready_state",
    "review_submit_generic_error_payload",
    "run_review_submit_task",
]
