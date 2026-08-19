"""Cancellation helpers for importer execution views and control plane."""

from __future__ import annotations

from typing import Any, Callable

from django.utils import timezone

from server.imports.models import ImportJob
from server.services.import_review_store import clear_db_review_state
from server.services.import_ui_summary import derive_terminal_result_state


def cancel_import_immediately(
    *,
    job: ImportJob,
    user_id: int,
    request_workflow_cancellation_fn: Callable[..., int],
    workflow_payload_fn: Callable[[ImportJob], dict[str, Any]],
    save_workflow_payload_fn: Callable[[ImportJob, dict[str, Any]], None],
    emit_import_notification_fn: Callable[..., None],
    clear_db_review_state_fn: Callable[[ImportJob], None] = clear_db_review_state,
) -> None:
    request_workflow_cancellation_fn(job=job)
    workflow = workflow_payload_fn(job)
    workflow["status"] = ImportJob.Status.FAILED
    workflow["finished_at"] = timezone.now().isoformat()
    save_workflow_payload_fn(job, workflow)
    clear_db_review_state_fn(job)
    job.review_rows = []
    result_summary = dict(job.result_summary or {})
    terminal_state = derive_terminal_result_state(
        status="failed",
        row_count=int(result_summary.get("row_count", 0) or 0),
        created_count=int(result_summary.get("created_count", 0) or 0),
        updated_count=int(result_summary.get("updated_count", 0) or 0),
        skipped_count=int(result_summary.get("skipped_count", 0) or 0),
        error_count=int(result_summary.get("error_count", 0) or 0),
        review_total_count=0,
        overflow_blocking=False,
        explicit_terminal_reason="cancelled",
    )
    result_summary.update(
        {
            "success": False,
            "review_count": 0,
            "review_overflow_count": 0,
            "review_total_count": 0,
            "review_pending_group_count": 0,
            "review_state": "none",
            "overflow_blocking": False,
            "review_disabled": False,
            "review_disabled_reason": "",
            **terminal_state,
        }
    )
    progress_detail = dict(job.progress_detail or {})
    progress_detail.update(
        {
            "phase": "done",
            "review_overflow_count": 0,
            "review_pending_group_count": 0,
            "review_state": "none",
            "overflow_blocking": False,
            "review_disabled": False,
            "review_disabled_reason": "",
            **terminal_state,
        }
    )
    job.result_summary = result_summary
    job.progress_detail = progress_detail
    job.status = ImportJob.Status.FAILED
    job.stage = ImportJob.Stage.EXECUTION
    job.progress = 100
    job.error_message = "This import was cancelled before completion."
    job.save(
        update_fields=[
            "review_rows",
            "result_summary",
            "progress_detail",
            "status",
            "stage",
            "progress",
            "error_message",
            "updated_at",
        ]
    )
    emit_import_notification_fn(
        event_type="import.execution_failed",
        user_id=user_id,
        title="Import cancelled",
        body=f"Your import for {job.filename} was cancelled before it could finish.",
        data={
            "session_id": str(job.id),
            "entity_type": str(job.detected_entity or ""),
        },
    )


def cancel_import_request(
    *,
    job: ImportJob,
    user_id: int,
    agency_id: int,
    build_import_status_payload_fn: Callable[..., dict[str, object]],
    execution_health_snapshot_fn: Callable[[ImportJob], dict[str, object]],
    cancel_import_immediately_fn: Callable[..., None],
    request_workflow_cancellation_fn: Callable[..., int],
    release_execution_slot_fn: Callable[..., object],
    execution_owner_for_job_fn: Callable[[object], object],
    dispatch_next_agency_import_fn: Callable[..., object],
    dispatch_queued_imports_fn: Callable[..., object],
    record_import_status_signal_fn: Callable[..., object],
    get_active_schema_fn: Callable[[], str],
) -> dict[str, object]:
    health = execution_health_snapshot_fn(job)
    can_cancel = bool(health.get("can_cancel", False))
    if not can_cancel:
        payload = build_import_status_payload_fn(session=job, agency_id=agency_id)
        payload["detail"] = "This import can no longer be cancelled."
        return payload

    waiting_for_worker = (
        job.status == ImportJob.Status.RUNNING
        and str(health.get("wait_state", "") or "") == "waiting_for_worker"
        and not str(health.get("last_phase_started_at", "") or "")
    )
    if job.status == ImportJob.Status.QUEUED or waiting_for_worker:
        cancel_import_immediately_fn(job=job, user_id=user_id)
        if job.status == ImportJob.Status.RUNNING:
            release_execution_slot_fn(
                agency_id=int(agency_id or 0),
                owner=execution_owner_for_job_fn(job.id),
            )
        dispatch_next_agency_import_fn(
            agency_id=int(agency_id or 0),
            schema=get_active_schema_fn(),
        )
        dispatch_queued_imports_fn(limit=2, max_global_running=2)
        refresh_from_db = getattr(job, "refresh_from_db", None)
        if callable(refresh_from_db):
            refresh_from_db()
        payload = build_import_status_payload_fn(session=job, agency_id=agency_id)
        record_import_status_signal_fn(
            event="cancel",
            terminal_reason="cancelled",
            cancel_requested=True,
        )
        payload["detail"] = "This import was cancelled."
        return payload

    request_workflow_cancellation_fn(job=job)
    record_import_status_signal_fn(
        event="cancel_request",
        wait_state=str(health.get("wait_state", "") or ""),
        cancel_requested=True,
    )
    payload = build_import_status_payload_fn(session=job, agency_id=agency_id)
    payload["cancellation_state"] = "cancel_requested"
    payload["detail"] = (
        "Cancellation requested. We'll stop this import as soon as the active work finishes."
    )
    return payload


__all__ = [
    "cancel_import_immediately",
    "cancel_import_request",
]
