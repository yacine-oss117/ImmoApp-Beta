"""Prepare, plan, load, and finalize runners for import Celery tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

import server.services.import_prepare_service as import_prepare_service
from server.api.notifications import NotificationPersistenceError
from server.imports.models import ImportChunkPhase
from server.services.import_chunk_workflow import workflow_params
from server.services.import_distributed_execution import load_chunk_phase, plan_chunk_phase
from server.services.import_finalize_service import finalize_distributed_import_job
from server.services.import_job_queue import (
    dispatch_next_agency_import,
    dispatch_queued_imports,
    execution_owner_for_job,
    release_execution_slot,
)
from server.services.import_job_topology import job_topology
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_phase_attempts import (
    ImportPhaseAttemptCancelled,
    StaleImportPhaseLeaseError,
    cancel_phase_attempt,
    claim_phase_attempt_started,
    complete_phase_attempt,
)
from server.services.import_prepare_common import DownloadToTemp
from server.services.import_type_inference import unsupported_child_only_import_message
from server.services.import_types import ImportResult, ReviewRowBuffer

from .tasks_core import logger, require_agency_id, task_context
from .tasks_import_failures import (
    friendly_import_failure_message,
    handle_phase_exception,
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


ChunkPhaseRunner = Callable[[ImportChunkPhase, int], dict[str, Any]]


def cleanup_prepared_artifact(artifact: object | None) -> None:
    if artifact is None:
        return
    temp_path = getattr(artifact, "temp_path", None)
    spool_dir = getattr(artifact, "spool_dir", None)
    if temp_path:
        try:
            temp_path.unlink()
        except OSError:
            pass
    if spool_dir:
        try:
            for path in sorted(Path(spool_dir).rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink(missing_ok=True)
                else:
                    path.rmdir()
            Path(spool_dir).rmdir()
        except OSError:
            pass


def run_import_prepare_phase_task(
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    schema: str | None = None,
    correlation_id: str | None = None,
    queue_import_dispatch_fn: QueueImportDispatchFn,
    download_to_temp_fn: DownloadToTemp,
) -> dict[str, Any]:
    agency_id = require_agency_id(agency_id, "import_prepare_phase_task")
    user = load_import_user(user_id)
    with task_context(
        schema,
        agency_id,
        actor_id=getattr(user, "id", None) if user else None,
        actor_role=str(getattr(user, "role", "") or None) if user else None,
        actor_is_owner=bool(getattr(user, "is_owner", False)) if user else False,
        correlation_id=correlation_id,
    ):
        service = load_import_service(user_id)
        if service is None:
            return {"session_id": session_id, "status": "failed", "error": "Invalid user"}
        job = service.get_job(session_id)
        if not job:
            return {"session_id": session_id, "status": "missing"}

        params = workflow_params(job)
        entity_type = normalize_import_entity_type(
            str(params.get("entity_type", job.detected_entity or "") or "")
        )
        skip_rows = int(params.get("skip_rows", 0) or 0)
        skip_review_rows = bool(params.get("skip_review_rows", False))
        corrections = params.get("corrections")
        if not isinstance(corrections, dict):
            corrections = {}

        artifact: object | None = None
        with ReviewRowBuffer() as review_rows:
            result = ImportResult(success=False)
            try:
                topology = job_topology(job)
                bundle_mode = topology.bundle_mode
                unsupported_message = unsupported_child_only_import_message(
                    {
                        "bundle_mode": bundle_mode,
                        "detected_entity": entity_type,
                    }
                )
                if unsupported_message:
                    mark_distributed_job_failed(
                        job=job,
                        user_id=user_id,
                        message=unsupported_message,
                        schema=schema,
                    )
                    return {
                        "session_id": str(job.id),
                        "status": "failed",
                        "error": unsupported_message,
                    }
                if bundle_mode == "same_side_bundle":
                    artifact = import_prepare_service.prepare_same_side_bundle_import(
                        job=job,
                        root_entity=topology.root_entity,
                        child_entity=topology.child_entity,
                        topology_side=topology.topology_side,
                        skip_rows=skip_rows,
                        skip_review_rows=skip_review_rows,
                        duplicate_strategy=str(params.get("duplicate_strategy", "skip") or "skip"),
                        corrections=corrections,
                        review_rows=review_rows,
                        result=result,
                        download_to_temp_fn=download_to_temp_fn,
                    )
                elif entity_type in {"demande", "offer"}:
                    artifact = import_prepare_service.prepare_child_only_import(
                        job=job,
                        entity_type=entity_type,
                        skip_rows=skip_rows,
                        skip_review_rows=skip_review_rows,
                        corrections=corrections,
                        review_rows=review_rows,
                        result=result,
                        download_to_temp_fn=download_to_temp_fn,
                    )
                else:
                    artifact = import_prepare_service.prepare_single_entity_import(
                        job=job,
                        user_id=user_id,
                        entity_type=entity_type,
                        skip_rows=skip_rows,
                        skip_review_rows=skip_review_rows,
                        duplicate_strategy=str(params.get("duplicate_strategy", "skip") or "skip"),
                        corrections=corrections,
                        review_rows=review_rows,
                        result=result,
                        download_to_temp_fn=download_to_temp_fn,
                    )
                from server.services.import_chunk_workflow import stage_prepared_artifact

                stage_prepared_artifact(
                    job=job,
                    artifact=artifact,
                    review_rows=review_rows,
                    errors=list(result.errors),
                    result=result,
                )
                cleanup_prepared_artifact(artifact)
                queue_import_dispatch_fn(
                    session_id=str(job.id),
                    user_id=user_id,
                    agency_id=agency_id,
                    schema=schema,
                    correlation_id=correlation_id,
                )
                return {"session_id": str(job.id), "status": "prepared"}
            except Exception as exc:
                cleanup_prepared_artifact(artifact)
                mark_distributed_job_failed(
                    job=job,
                    user_id=user_id,
                    message=friendly_import_failure_message(exc),
                    schema=schema,
                )
                raise


def _run_chunk_phase_task(
    *,
    _task: object,
    session_id: str,
    user_id: int,
    agency_id: int | None,
    phase_id: int,
    schema: str | None,
    correlation_id: str | None,
    phase_name: str,
    runner: ChunkPhaseRunner,
    queue_import_dispatch_fn: QueueImportDispatchFn,
) -> dict[str, Any]:
    agency_id = require_agency_id(agency_id, phase_name)
    user = load_import_user(user_id)
    with task_context(
        schema,
        agency_id,
        actor_id=getattr(user, "id", None) if user else None,
        actor_role=str(getattr(user, "role", "") or None) if user else None,
        actor_is_owner=bool(getattr(user, "is_owner", False)) if user else False,
        correlation_id=correlation_id,
    ):
        service = load_import_service(user_id)
        if service is None:
            return {"session_id": session_id, "status": "failed", "error": "Invalid user"}
        job = service.get_job(session_id)
        if not job:
            return {"session_id": session_id, "status": "missing"}
        phase = claim_phase_attempt_started(
            phase_id=phase_id,
            task_id=str(getattr(getattr(_task, "request", None), "id", "") or ""),
        )
        if phase is None:
            return {"session_id": session_id, "phase_id": phase_id, "status": "skipped"}
        try:
            metrics = runner(phase, user_id)
            if not complete_phase_attempt(
                phase_id=phase_id,
                attempt_id=str(phase.lease_token or ""),
                metrics_payload=metrics,
            ):
                return {"session_id": str(job.id), "phase_id": phase_id, "status": "stale"}
            queue_import_dispatch_fn(
                session_id=str(job.id),
                user_id=user_id,
                agency_id=agency_id,
                schema=schema,
                correlation_id=correlation_id,
            )
            return {"session_id": str(job.id), "phase_id": phase_id, "status": "completed"}
        except ImportPhaseAttemptCancelled:
            cancelled = cancel_phase_attempt(
                phase_id=phase_id,
                attempt_id=str(phase.lease_token or ""),
                error_payload={"code": "import_phase_cancelled"},
            )
            status = "cancelled" if cancelled else "stale"
            return {"session_id": str(job.id), "phase_id": phase_id, "status": status}
        except StaleImportPhaseLeaseError:
            return {"session_id": str(job.id), "phase_id": phase_id, "status": "stale"}
        except Exception as exc:
            try:
                handle_phase_exception(
                    _task=_task,
                    job=job,
                    phase_id=phase_id,
                    lease_token=str(phase.lease_token or ""),
                    user_id=user_id,
                    exc=exc,
                    schema=schema,
                )
            except StaleImportPhaseLeaseError:
                return {"session_id": str(job.id), "phase_id": phase_id, "status": "stale"}


def run_import_plan_chunk_task(
    *,
    _task: object,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    phase_id: int,
    schema: str | None = None,
    correlation_id: str | None = None,
    queue_import_dispatch_fn: QueueImportDispatchFn,
) -> dict[str, Any]:
    return _run_chunk_phase_task(
        _task=_task,
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        phase_id=phase_id,
        schema=schema,
        correlation_id=correlation_id,
        phase_name="import_plan_chunk_task",
        runner=lambda phase, user_id: plan_chunk_phase(phase=phase, user_id=user_id),
        queue_import_dispatch_fn=queue_import_dispatch_fn,
    )


def run_import_load_chunk_task(
    *,
    _task: object,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    phase_id: int,
    schema: str | None = None,
    correlation_id: str | None = None,
    queue_import_dispatch_fn: QueueImportDispatchFn,
) -> dict[str, Any]:
    return _run_chunk_phase_task(
        _task=_task,
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        phase_id=phase_id,
        schema=schema,
        correlation_id=correlation_id,
        phase_name="import_load_chunk_task",
        runner=lambda phase, user_id: load_chunk_phase(phase=phase, user_id=user_id),
        queue_import_dispatch_fn=queue_import_dispatch_fn,
    )


def run_import_finalize_job_task(
    *,
    _task: object,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    agency_id = require_agency_id(agency_id, "import_finalize_job_task")
    user = load_import_user(user_id)
    with task_context(
        schema,
        agency_id,
        actor_id=getattr(user, "id", None) if user else None,
        actor_role=str(getattr(user, "role", "") or None) if user else None,
        actor_is_owner=bool(getattr(user, "is_owner", False)) if user else False,
        correlation_id=correlation_id,
    ):
        service = load_import_service(user_id)
        if service is None:
            return {"session_id": session_id, "status": "failed", "error": "Invalid user"}
        job = service.get_job(session_id)
        if not job:
            return {"session_id": session_id, "status": "missing"}
        try:
            summary = finalize_distributed_import_job(job=job, user_id=user_id)
            release_execution_slot(
                agency_id=int(getattr(job, "agency_id", 0) or 0),
                owner=execution_owner_for_job(job.id),
            )
            dispatch_next_agency_import(
                agency_id=int(getattr(job, "agency_id", 0) or 0),
                schema=schema,
            )
            dispatch_queued_imports(limit=2, max_global_running=2)
            return {"session_id": str(job.id), "status": str(job.status), **summary}
        except NotificationPersistenceError as exc:
            logger.warning(
                "import_finalize_job_task deferred terminal success commit for job %s because canonical notification persistence failed",
                job.id,
                exc_info=True,
            )
            retry = getattr(_task, "retry", None)
            if callable(retry):
                raise retry(exc=exc, countdown=5) from exc
            raise
        except Exception as exc:
            logger.exception("import_finalize_job_task failed for job %s", job.id)
            mark_distributed_job_failed(
                job=job,
                user_id=user_id,
                message=friendly_import_failure_message(exc),
                schema=schema,
            )
            raise


__all__ = [
    "cleanup_prepared_artifact",
    "run_import_finalize_job_task",
    "run_import_load_chunk_task",
    "run_import_plan_chunk_task",
    "run_import_prepare_phase_task",
]
