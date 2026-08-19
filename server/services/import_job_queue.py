"""Agency-scoped importer execution queueing."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core.data import tenant_work_lease
from server.api.tasks_core import enqueue_import_task
from server.imports.models import ImportJob
from server.pg.uow import get_current_schema, get_uow, use_security_context
from server.services.import_chunk_workflow import save_workflow_payload, workflow_payload

_LEASE_TASK_NAME = "imports_execute"
_STREAM_KEY = "default"
_LEASE_SECONDS = 30 * 60
_MAX_IN_FLIGHT = 1


@dataclass(frozen=True)
class QueueClaimResult:
    status: str
    queue_position: int
    agency_queue_depth: int


def execution_owner_for_job(job_id: object) -> str:
    return f"import-job:{job_id}"


def agency_queue_depth(*, agency_id: int) -> int:
    return int(
        ImportJob.objects.filter(
            agency_id=int(agency_id),
            status=ImportJob.Status.QUEUED,
        ).count()
    )


def global_running_import_count() -> int:
    return int(ImportJob.objects.filter(status=ImportJob.Status.RUNNING).count())


def _reserve_execution_slot(*, agency_id: int, owner: str) -> bool:
    with use_security_context(agency_id=int(agency_id), is_superuser=False):
        with get_uow().transaction(actor=f"import-lease-reserve:{agency_id}") as session:
            _active_owner, reserved = tenant_work_lease.reserve_stream_slot(
                session,
                task_name=_LEASE_TASK_NAME,
                agency_id=int(agency_id),
                stream_key=_STREAM_KEY,
                provisional_owner=str(owner),
                lease_seconds=_LEASE_SECONDS,
                max_in_flight=_MAX_IN_FLIGHT,
            )
            return bool(reserved)


def _recover_and_reserve_execution_slot(*, agency_id: int, owner: str) -> bool:
    with use_security_context(agency_id=int(agency_id), is_superuser=False):
        with get_uow().transaction(actor=f"import-lease-recover:{agency_id}") as session:
            tenant_work_lease.clear_stream_slot(
                session,
                task_name=_LEASE_TASK_NAME,
                agency_id=int(agency_id),
                stream_key=_STREAM_KEY,
            )
            _active_owner, reserved = tenant_work_lease.reserve_stream_slot(
                session,
                task_name=_LEASE_TASK_NAME,
                agency_id=int(agency_id),
                stream_key=_STREAM_KEY,
                provisional_owner=str(owner),
                lease_seconds=_LEASE_SECONDS,
                max_in_flight=_MAX_IN_FLIGHT,
            )
            return bool(reserved)


def release_execution_slot(*, agency_id: int, owner: str) -> None:
    with use_security_context(agency_id=int(agency_id), is_superuser=False):
        with get_uow().transaction(actor=f"import-lease-release:{agency_id}") as session:
            tenant_work_lease.release_stream_slot(
                session,
                task_name=_LEASE_TASK_NAME,
                agency_id=int(agency_id),
                stream_key=_STREAM_KEY,
                lease_owner=str(owner),
            )


def queue_position_for_job(job: ImportJob) -> int:
    if job.status != ImportJob.Status.QUEUED:
        return 0
    return (
        int(
            ImportJob.objects.filter(
                agency_id=int(getattr(job, "agency_id", 0) or 0),
                status=ImportJob.Status.QUEUED,
                created_at__lt=job.created_at,
            ).count()
        )
        + 1
    )


def mark_job_queued(
    job: ImportJob,
    *,
    execution_profile: str,
) -> QueueClaimResult:
    queue_depth = 0
    payload = workflow_payload(job)
    payload["queued_at"] = timezone.now().isoformat()
    payload["cancel_requested"] = False
    payload["execution_profile"] = str(execution_profile or "")
    payload["status"] = ImportJob.Status.QUEUED
    job.status = ImportJob.Status.QUEUED
    job.stage = ImportJob.Stage.EXECUTION
    job.progress = 0
    progress_detail = dict(job.progress_detail or {})
    progress_detail.update(
        {
            "phase": "queued",
            "current_chunk": 0,
            "execution_profile": str(execution_profile or ""),
        }
    )
    job.progress_detail = progress_detail
    job.save(
        update_fields=[
            "status",
            "stage",
            "progress",
            "progress_detail",
            "updated_at",
        ]
    )
    queue_depth = agency_queue_depth(agency_id=int(getattr(job, "agency_id", 0) or 0))
    payload["agency_queue_depth"] = queue_depth
    save_workflow_payload(job, payload)
    return QueueClaimResult(
        status="queued",
        queue_position=queue_position_for_job(job),
        agency_queue_depth=queue_depth,
    )


def mark_job_running(
    job: ImportJob,
    *,
    execution_profile: str,
) -> None:
    payload = workflow_payload(job)
    payload["cancel_requested"] = False
    payload["execution_profile"] = str(execution_profile or "")
    payload["status"] = ImportJob.Status.RUNNING
    payload["queued_at"] = None
    payload["agency_queue_depth"] = 0
    save_workflow_payload(job, payload)
    job.status = ImportJob.Status.RUNNING
    job.stage = ImportJob.Stage.EXECUTION
    progress_detail = dict(job.progress_detail or {})
    progress_detail["execution_profile"] = str(execution_profile or "")
    if str(progress_detail.get("phase", "") or "") == "":
        progress_detail["phase"] = "queued"
    job.progress_detail = progress_detail
    job.save(
        update_fields=[
            "status",
            "stage",
            "progress_detail",
            "updated_at",
        ]
    )


def claim_execution_or_queue(
    job: ImportJob,
    *,
    execution_profile: str,
    force_queue: bool = False,
) -> QueueClaimResult:
    agency_id = int(getattr(job, "agency_id", 0) or 0)
    if force_queue:
        if agency_queue_depth(agency_id=agency_id) >= 1 and job.status != ImportJob.Status.QUEUED:
            return QueueClaimResult(status="full", queue_position=0, agency_queue_depth=1)
        return mark_job_queued(job, execution_profile=execution_profile)
    owner = execution_owner_for_job(job.id)
    if _reserve_execution_slot(agency_id=agency_id, owner=owner):
        mark_job_running(job, execution_profile=execution_profile)
        return QueueClaimResult(
            status="running",
            queue_position=0,
            agency_queue_depth=agency_queue_depth(agency_id=agency_id),
        )
    if not ImportJob.objects.filter(
        agency_id=agency_id,
        status=ImportJob.Status.RUNNING,
    ).exists() and _recover_and_reserve_execution_slot(agency_id=agency_id, owner=owner):
        mark_job_running(job, execution_profile=execution_profile)
        return QueueClaimResult(
            status="running",
            queue_position=0,
            agency_queue_depth=agency_queue_depth(agency_id=agency_id),
        )
    if agency_queue_depth(agency_id=agency_id) >= 1 and job.status != ImportJob.Status.QUEUED:
        return QueueClaimResult(status="full", queue_position=0, agency_queue_depth=1)
    return mark_job_queued(job, execution_profile=execution_profile)


def dispatch_next_agency_import(*, agency_id: int, schema: str | None = None) -> bool:
    with transaction.atomic():
        queued_job = (
            ImportJob.objects.select_for_update()
            .filter(
                agency_id=int(agency_id),
                status=ImportJob.Status.QUEUED,
            )
            .order_by("created_at", "id")
            .first()
        )
        if queued_job is None:
            return False
        owner = execution_owner_for_job(queued_job.id)
        if not _reserve_execution_slot(agency_id=int(agency_id), owner=owner):
            if ImportJob.objects.filter(
                agency_id=int(agency_id),
                status=ImportJob.Status.RUNNING,
            ).exclude(id=queued_job.id).exists() or not _recover_and_reserve_execution_slot(
                agency_id=int(agency_id),
                owner=owner,
            ):
                return False
        payload = workflow_payload(queued_job)
        params = dict(payload.get("params", {}) or {})
        mark_job_running(
            queued_job,
            execution_profile=str(payload.get("execution_profile", "red") or "red"),
        )
    from server.api.tasks_import import import_execute_task

    async_result = enqueue_import_task(
        import_execute_task,
        session_id=str(queued_job.id),
        user_id=int(getattr(queued_job, "user_id", 0) or 0),
        agency_id=int(agency_id),
        entity_type=str(params.get("entity_type", queued_job.detected_entity or "") or ""),
        column_mapping=dict(params.get("column_mapping", queued_job.column_mapping or {}) or {}),
        skip_rows=int(params.get("skip_rows", 0) or 0),
        duplicate_strategy=str(params.get("duplicate_strategy", "skip") or "skip"),
        skip_review_rows=bool(params.get("skip_review_rows", False)),
        corrections=params.get("corrections"),
        execution_cost=int(payload.get("execution_cost", 1) or 1),
        schema=schema or get_current_schema(),
        correlation_id=None,
    )
    ImportJob.objects.filter(id=queued_job.id).update(
        task_id=async_result.id, updated_at=timezone.now()
    )
    return True


def dispatch_queued_imports(*, limit: int = 5, max_global_running: int | None = None) -> int:
    dispatched = 0
    queued_agencies = list(
        ImportJob.objects.filter(status=ImportJob.Status.QUEUED)
        .order_by("created_at", "id")
        .values_list("agency_id", flat=True)
        .distinct()
    )
    for agency_id in queued_agencies:
        if max_global_running is not None and global_running_import_count() >= int(
            max_global_running
        ):
            break
        if dispatch_next_agency_import(agency_id=int(agency_id), schema=get_current_schema()):
            dispatched += 1
        if dispatched >= max(1, int(limit)):
            break
    return dispatched


__all__ = [
    "QueueClaimResult",
    "agency_queue_depth",
    "claim_execution_or_queue",
    "dispatch_next_agency_import",
    "dispatch_queued_imports",
    "execution_owner_for_job",
    "global_running_import_count",
    "queue_position_for_job",
    "release_execution_slot",
]
