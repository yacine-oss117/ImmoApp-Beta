"""Failure and retry helpers for importer Celery tasks."""

from __future__ import annotations

from typing import NoReturn

from django.utils import timezone

from server.imports.models import ImportArtifactManifest, ImportChunkPhase, ImportJob
from server.services.import_chunk_workflow import (
    StaleImportPhaseLeaseError,
    load_jsonl_manifest_rows,
    request_workflow_cancellation,
    save_workflow_payload,
    workflow_payload,
)
from server.services.import_execution_state import friendly_import_error_message
from server.services.import_job_queue import (
    dispatch_next_agency_import,
    dispatch_queued_imports,
    execution_owner_for_job,
    release_execution_slot,
)
from server.services.import_notifications import emit_import_notification
from server.services.import_phase_attempts import fail_phase_attempt
from server.services.import_review_store import clear_db_review_state

from .tasks_core import _TASK_RETRYABLE_EXCEPTIONS


def friendly_import_failure_message(exc: Exception) -> str:
    return friendly_import_error_message(exc)


def collect_distributed_failure_errors(job: ImportJob) -> list[dict[str, object]]:
    collected: list[dict[str, object]] = []
    manifests = list(
        ImportArtifactManifest.objects.filter(
            job=job,
            artifact_kind__in=["errors", "load_errors"],
        ).order_by("chunk__chunk_role", "chunk__ordinal", "id")
    )
    for manifest in manifests:
        for row in load_jsonl_manifest_rows(manifest):
            if isinstance(row, dict):
                collected.append({str(key): value for key, value in row.items()})
    failed_phases = list(
        ImportChunkPhase.objects.filter(
            chunk__job=job,
            status=ImportChunkPhase.Status.FAILED,
        )
        .select_related("chunk")
        .order_by("chunk__chunk_role", "chunk__ordinal", "id")
    )
    for phase in failed_phases:
        error_payload = dict(phase.error_payload or {})
        for row in list(error_payload.get("row_errors", []) or []):
            if isinstance(row, dict):
                collected.append({str(key): value for key, value in row.items()})
        message = str(error_payload.get("message", "") or "").strip()
        if message:
            collected.append(
                {
                    "row": 0,
                    "errors": [message],
                    "phase": str(phase.phase or ""),
                    "chunk_role": str(phase.chunk.chunk_role or ""),
                }
            )
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in collected:
        row_value = item.get("row", 0)
        if isinstance(row_value, bool):
            row_key = str(int(row_value))
        elif isinstance(row_value, (int, float)):
            row_key = str(int(row_value))
        elif isinstance(row_value, str):
            try:
                row_key = str(int(row_value.strip() or "0"))
            except ValueError:
                row_key = "0"
        else:
            row_key = "0"
        raw_errors = item.get("errors", [])
        errors_list = raw_errors if isinstance(raw_errors, list) else []
        errors_key = " | ".join(str(value) for value in errors_list)
        phase_key = str(item.get("phase", "") or "")
        dedupe_key = (row_key, errors_key, phase_key)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(item)
    return deduped


def mark_distributed_job_failed(
    *,
    job: ImportJob,
    user_id: int,
    message: str,
    schema: str | None = None,
) -> None:
    request_workflow_cancellation(job=job)
    clear_db_review_state(job)
    job.review_rows = []
    workflow = workflow_payload(job)
    workflow["status"] = ImportJob.Status.FAILED
    workflow["finished_at"] = timezone.now().isoformat()
    save_workflow_payload(job, workflow)
    failure_errors = collect_distributed_failure_errors(job)
    result_summary = dict(job.result_summary or {})
    result_summary["success"] = False
    result_summary["error_count"] = max(
        int(result_summary.get("error_count", 0) or 0),
        len(failure_errors),
        1,
    )
    result_summary["errors"] = failure_errors
    result_summary["review_count"] = 0
    result_summary["review_overflow_count"] = 0
    result_summary["review_total_count"] = 0
    result_summary["review_pending_group_count"] = 0
    result_summary["review_state"] = "none"
    result_summary["overflow_blocking"] = False
    result_summary["review_disabled"] = False
    result_summary["review_disabled_reason"] = ""
    job.result_summary = result_summary
    progress_detail = dict(job.progress_detail or {})
    progress_detail["phase"] = str(progress_detail.get("phase", "executing") or "executing")
    progress_detail["error_count"] = max(
        int(progress_detail.get("error_count", 0) or 0),
        len(failure_errors),
        1,
    )
    progress_detail["review_overflow_count"] = 0
    progress_detail["review_pending_group_count"] = 0
    progress_detail["review_state"] = "none"
    progress_detail["overflow_blocking"] = False
    progress_detail["review_disabled"] = False
    progress_detail["review_disabled_reason"] = ""
    job.progress_detail = progress_detail
    job.status = ImportJob.Status.FAILED
    job.stage = ImportJob.Stage.EXECUTION
    job.progress = max(0, int(job.progress or 0))
    job.error_message = message
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
    release_execution_slot(
        agency_id=int(getattr(job, "agency_id", 0) or 0),
        owner=execution_owner_for_job(job.id),
    )
    dispatch_next_agency_import(
        agency_id=int(getattr(job, "agency_id", 0) or 0),
        schema=schema,
    )
    dispatch_queued_imports(limit=2, max_global_running=2)
    emit_import_notification(
        event_type="import.execution_failed",
        user_id=user_id,
        title="Import failed",
        body=f"Your import for {job.filename} failed.",
        data={
            "session_id": str(job.id),
            "entity_type": str(job.detected_entity or ""),
        },
    )


def phase_retryable(exc: Exception) -> bool:
    return isinstance(exc, _TASK_RETRYABLE_EXCEPTIONS)


def handle_phase_exception(
    *,
    _task: object,
    job: ImportJob,
    phase_id: int | None,
    lease_token: str = "",
    user_id: int,
    exc: Exception,
    schema: str | None = None,
) -> NoReturn:
    current_retries = int(getattr(getattr(_task, "request", None), "retries", 0) or 0)
    max_retries = int(getattr(_task, "max_retries", 0) or 0)
    error_payload = {
        "message": str(exc),
        "retryable": phase_retryable(exc),
        "retries": current_retries,
        "max_retries": max_retries,
    }
    row_errors = [
        dict(item) for item in list(getattr(exc, "row_errors", []) or []) if isinstance(item, dict)
    ]
    if row_errors:
        error_payload["row_errors"] = row_errors
    if phase_id is not None and phase_retryable(exc) and current_retries < max_retries:
        ImportChunkPhase.objects.filter(id=phase_id).update(
            status=ImportChunkPhase.Status.QUEUED,
            error_payload=error_payload,
            lease_token="",
            heartbeat_at=None,
            lease_expires_at=None,
            finished_at=None,
        )
        raise exc
    if phase_id is not None:
        if not fail_phase_attempt(
            phase_id=phase_id,
            attempt_id=lease_token,
            error_payload=error_payload,
        ):
            raise StaleImportPhaseLeaseError(
                f"Chunk phase {phase_id} lost its lease before the failure could be recorded."
            )
    mark_distributed_job_failed(
        job=job,
        user_id=user_id,
        message=friendly_import_failure_message(exc),
        schema=schema,
    )
    raise exc


__all__ = [
    "collect_distributed_failure_errors",
    "friendly_import_failure_message",
    "handle_phase_exception",
    "mark_distributed_job_failed",
    "phase_retryable",
]
