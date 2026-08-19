"""Execute-task orchestration for import Celery tasks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from server.imports.models import ImportJob
from server.services import tenant_resource_governor
from server.services.import_chunk_workflow import (
    initialize_distributed_workflow,
    save_workflow_payload,
    workflow_payload,
)
from server.services.import_constants import normalize_duplicate_strategy
from server.services.import_execution_governor import effective_import_runtime_profile
from server.services.import_job_queue import claim_execution_or_queue
from server.services.import_job_topology import job_topology
from server.services.import_mapping import canonicalize_column_mapping
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_review_store import clear_db_review_state
from server.services.import_type_inference import unsupported_child_only_import_message

from .tasks_core import (
    import_execution_lock,
    logger,
    require_agency_id,
    task_context,
)
from .tasks_import_failures import (
    friendly_import_failure_message,
    mark_distributed_job_failed,
)
from .tasks_import_helpers import load_import_service, load_import_user


class QueueImportDispatchFn(Protocol):
    def __call__(
        self,
        *,
        session_id: str,
        user_id: int,
        agency_id: int,
        schema: str | None,
        correlation_id: str | None,
    ) -> None: ...


class EnqueuePreparePhaseTaskFn(Protocol):
    def __call__(
        self,
        *,
        session_id: str,
        user_id: int,
        agency_id: int,
        schema: str | None,
        correlation_id: str | None,
    ) -> None: ...


def run_import_execute_task(
    *,
    _task: object,
    _call_marker: object | None = None,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    entity_type: str,
    column_mapping: dict[str, str],
    skip_rows: int = 0,
    duplicate_strategy: str = "skip",
    skip_review_rows: bool = False,
    corrections: dict[str, dict[str, Any]] | None = None,
    execution_cost: int = 1,
    schema: str | None = None,
    correlation_id: str | None = None,
    queue_import_dispatch_fn: QueueImportDispatchFn,
    enqueue_prepare_phase_task_fn: EnqueuePreparePhaseTaskFn,
    emit_import_notification_fn: Callable[..., None],
) -> dict[str, Any]:
    agency_id = require_agency_id(agency_id, "import_execute_task")
    user = load_import_user(user_id)
    with task_context(
        schema,
        agency_id,
        actor_id=getattr(user, "id", None) if user else None,
        actor_role=str(getattr(user, "role", "") or None) if user else None,
        actor_is_owner=bool(getattr(user, "is_owner", False)) if user else False,
        correlation_id=correlation_id,
    ):
        try:
            service = load_import_service(user_id)
            if service is None:
                return {"session_id": session_id, "status": "failed", "error": "Invalid user"}

            job = service.get_job(session_id)
            if not job:
                return {"session_id": session_id, "status": "missing"}
            current_task_id = str(getattr(getattr(_task, "request", None), "id", "") or "")
            if not current_task_id:
                current_task_id = str(
                    getattr(getattr(_call_marker, "request", None), "id", "") or ""
                )
            current_workflow = workflow_payload(job)
            if current_task_id and str(job.task_id or "").strip() not in {"", current_task_id}:
                logger.info(
                    "Ignoring stale import_execute_task for job %s: task_id=%s current=%s",
                    job.id,
                    current_task_id,
                    job.task_id,
                )
                return {"session_id": str(job.id), "status": "stale_ignored"}
            if (
                job.status not in {ImportJob.Status.RUNNING, ImportJob.Status.QUEUED}
                and str(current_workflow.get("finished_at", "") or "").strip()
            ):
                logger.info(
                    "Ignoring terminal import_execute_task for job %s with status %s",
                    job.id,
                    job.status,
                )
                return {"session_id": str(job.id), "status": "terminal_ignored"}

            normalized_entity_type = normalize_import_entity_type(entity_type)
            unsupported_message = unsupported_child_only_import_message(
                {
                    "bundle_mode": job_topology(job).bundle_mode,
                    "detected_entity": normalized_entity_type,
                }
            )
            if unsupported_message:
                job.status = ImportJob.Status.FAILED
                job.progress = 0
                job.error_message = unsupported_message
                job.save(update_fields=["status", "progress", "error_message", "updated_at"])
                return {"session_id": session_id, "status": "failed", "error": unsupported_message}
            normalized_duplicate_strategy = normalize_duplicate_strategy(duplicate_strategy)
            normalized_column_mapping = canonicalize_column_mapping(
                column_mapping=column_mapping,
                detected_columns=job.detected_columns or [],
                final_inference=(job.inference_summary or {}).get("final_inference", {}),
            )
            if not normalized_column_mapping:
                error = "column_mapping required"
                job.status = ImportJob.Status.FAILED
                job.progress = 0
                job.error_message = error
                job.save()
                return {"session_id": session_id, "status": "failed", "error": error}
            workflow_state, created_new_workflow = initialize_distributed_workflow(
                job=job,
                entity_type=normalized_entity_type,
                duplicate_strategy=normalized_duplicate_strategy,
                skip_rows=skip_rows,
                skip_review_rows=skip_review_rows,
                corrections=corrections,
            )
            workflow_state["execution_cost"] = int(execution_cost or 1)
            workflow_state["admission_mode"] = "normal"
            workflow_state["params"] = {
                **dict(workflow_state.get("params", {}) or {}),
                "column_mapping": dict(normalized_column_mapping),
            }
            save_workflow_payload(job, workflow_state)
            if job.status not in {ImportJob.Status.RUNNING, ImportJob.Status.QUEUED}:
                claim = claim_execution_or_queue(
                    job,
                    execution_profile=effective_import_runtime_profile().name,
                )
                if claim.status == "full":
                    return {
                        "session_id": str(job.id),
                        "status": "failed",
                        "error": "Another import is queued for this agency.",
                    }
                if claim.status == "queued":
                    return {
                        "session_id": str(job.id),
                        "status": "queued",
                        "queue_position": claim.queue_position,
                        "agency_queue_depth": claim.agency_queue_depth,
                    }
            elif job.status == ImportJob.Status.QUEUED:
                return {
                    "session_id": str(job.id),
                    "status": "queued",
                    "queue_position": 1,
                    "agency_queue_depth": 1,
                }

            with import_execution_lock(schema, agency_id) as locked:
                if not locked:
                    error = "Import execution lock unavailable for this agency."
                    mark_distributed_job_failed(
                        job=job,
                        user_id=user_id,
                        message=error,
                        schema=schema,
                    )
                    return {"session_id": session_id, "status": "failed", "error": error}
                job.status = ImportJob.Status.RUNNING
                job.stage = ImportJob.Stage.EXECUTION
                job.progress = 0
                job.error_message = None
                clear_db_review_state(job)
                job.review_rows = []
                job.detected_entity = normalized_entity_type
                job.column_mapping = normalized_column_mapping
                job.progress_detail = {
                    **dict(job.progress_detail or {}),
                    "rows_total": int((job.result_summary or {}).get("row_count") or 0),
                    "rows_processed": 0,
                    "rows_created": 0,
                    "rows_updated": 0,
                    "rows_skipped": 0,
                    "rows_review": 0,
                    "current_chunk": 0,
                    "chunks_total": 0,
                    "phase": "queued",
                    "bundle_mode": job_topology(job).bundle_mode,
                }
                job.save()

            emit_import_notification_fn(
                event_type="import.execution_started",
                user_id=user_id,
                title="Import started",
                body=f"Execution started for {job.filename}.",
                data={
                    "session_id": str(job.id),
                    "entity_type": normalized_entity_type,
                    "queue_name": "imports",
                    "execution_profile": effective_import_runtime_profile().name,
                },
            )
            if created_new_workflow:
                enqueue_prepare_phase_task_fn(
                    session_id=str(job.id),
                    user_id=user_id,
                    agency_id=agency_id,
                    schema=schema,
                    correlation_id=correlation_id,
                )
            else:
                queue_import_dispatch_fn(
                    session_id=str(job.id),
                    user_id=user_id,
                    agency_id=agency_id,
                    schema=schema,
                    correlation_id=correlation_id,
                )
            return {
                "session_id": str(job.id),
                "status": str(job.status),
                "task_id": str(job.task_id or getattr(getattr(_task, "request", None), "id", "")),
            }
        except Exception as exc:
            logger.exception("import_execute_task failed")
            if "job" in locals() and job:
                mark_distributed_job_failed(
                    job=job,
                    user_id=user_id,
                    message=friendly_import_failure_message(exc),
                    schema=schema,
                )
            raise
        finally:
            tenant_resource_governor.note_work_completed(
                budget_name="import_execute",
                agency_id=int(agency_id),
                cost=max(1, int(execution_cost or 1)),
            )


__all__ = ["run_import_execute_task"]
