"""Maintenance tasks (purge/cleanup)."""

from __future__ import annotations

from typing import Any

from .adaptive_batch import adaptive_batch_process
from .tasks_core import iter_active_agency_batches, logger, task_decorator


@task_decorator()
def purge_old_audit_logs_task(_task: object, retention_days: int = 90) -> dict[str, object]:
    """
    Purge audit logs older than retention_days for ALL agencies.

    This is a scheduled maintenance task that runs daily. It iterates
    through all active agencies and deletes old logs per-agency (RLS scoped).
    """
    from core.data import audit_repository
    from server.pg.uow import admin_transaction, get_uow, use_security_context

    total_deleted = 0
    agencies_processed = 0
    pages_processed = 0

    def _purge_for_agency(aid: int) -> None:
        nonlocal total_deleted, agencies_processed
        with use_security_context(agency_id=aid, is_superuser=False):
            with get_uow().transaction() as session:
                deleted = audit_repository.purge_old_audit_logs(session, retention_days)
                total_deleted += deleted
                agencies_processed += 1

    with admin_transaction() as session:
        for agency_batch in iter_active_agency_batches(session, batch_size=500):
            pages_processed += 1
            adaptive_batch_process(
                agency_batch,
                _purge_for_agency,
                label="maintenance.audit_purge",
            )

    logger.info(
        "Audit log retention purge complete: %s logs deleted across %s agencies (%s pages)",
        total_deleted,
        agencies_processed,
        pages_processed,
    )
    return {
        "deleted": total_deleted,
        "agencies": agencies_processed,
        "pages": pages_processed,
        "retention_days": retention_days,
    }


@task_decorator()
def purge_old_auth_events_task(_task: object, retention_days: int = 90) -> dict[str, object]:
    """Purge old auth security events across all agencies."""
    from server.services import auth_events

    deleted = auth_events.purge_old_auth_events(retention_days=retention_days)
    logger.info(
        "Auth security events purge complete: %s records deleted (retention=%s days)",
        deleted,
        retention_days,
    )
    return {"deleted": deleted, "retention_days": retention_days}


@task_decorator()
def purge_deleted_storage_objects_task(
    _task: object, retention_days: int = 30, batch_size: int = 200
) -> dict[str, object]:
    """Purge deleted storage objects from object storage."""
    from server.pg.uow import admin_transaction, use_security_context
    from server.services import storage

    total_deleted = 0
    agencies_processed = 0
    pages_processed = 0

    def _purge_for_agency(aid: int) -> None:
        nonlocal total_deleted, agencies_processed
        with use_security_context(agency_id=aid, is_superuser=False):
            deleted = storage.purge_deleted_objects(
                older_than_days=retention_days,
                limit=batch_size,
            )
            total_deleted += deleted
            agencies_processed += 1

    with admin_transaction() as session:
        for agency_batch in iter_active_agency_batches(session, batch_size=500):
            pages_processed += 1
            adaptive_batch_process(
                agency_batch,
                _purge_for_agency,
                label="maintenance.storage_deleted",
            )

    logger.info(
        "Storage purge complete: %s objects deleted across %s agencies (%s pages)",
        total_deleted,
        agencies_processed,
        pages_processed,
    )
    return {
        "deleted": total_deleted,
        "agencies": agencies_processed,
        "pages": pages_processed,
        "retention_days": retention_days,
    }


@task_decorator()
def purge_pending_storage_objects_task(
    _task: object, retention_hours: int = 24, batch_size: int = 200
) -> dict[str, object]:
    """Expire stale pending uploads that never completed."""
    from server.pg.uow import admin_transaction, use_security_context
    from server.services import storage

    total_deleted = 0
    agencies_processed = 0
    pages_processed = 0

    def _purge_for_agency(aid: int) -> None:
        nonlocal total_deleted, agencies_processed
        with use_security_context(agency_id=aid, is_superuser=False):
            deleted = storage.purge_pending_objects(
                older_than_hours=retention_hours,
                limit=batch_size,
            )
            total_deleted += deleted
            agencies_processed += 1

    with admin_transaction() as session:
        for agency_batch in iter_active_agency_batches(session, batch_size=500):
            pages_processed += 1
            adaptive_batch_process(
                agency_batch,
                _purge_for_agency,
                label="maintenance.storage_pending",
            )

    logger.info(
        "Pending storage purge complete: %s objects expired across %s agencies (%s pages)",
        total_deleted,
        agencies_processed,
        pages_processed,
    )
    return {
        "deleted": total_deleted,
        "agencies": agencies_processed,
        "pages": pages_processed,
        "retention_hours": retention_hours,
    }


@task_decorator()
def purge_idempotency_records_task(_task: object, limit: int = 2000) -> dict[str, object]:
    """Purge expired API idempotency records."""
    from server.api.idempotency_engine import purge_expired_idempotency_records

    deleted = purge_expired_idempotency_records(limit=max(100, int(limit)))
    logger.info("Idempotency purge complete: %s records removed", deleted)
    return {"deleted": deleted}


@task_decorator()
def expire_pending_registration_requests_task(
    _task: object,
    older_than_days: int = 30,
) -> dict[str, object]:
    """Expire stale pending registration requests and expired pending invites."""
    from server.services import registration_lifecycle

    expired_registrations = registration_lifecycle.expire_pending_registrations(
        older_than_days=max(1, int(older_than_days))
    )
    expired_invites = registration_lifecycle.expire_pending_invites()
    logger.info(
        "Registration maintenance complete: %s registrations expired, %s invites expired",
        expired_registrations,
        expired_invites,
    )
    return {
        "expired_registrations": int(expired_registrations),
        "expired_invites": int(expired_invites),
    }


@task_decorator(name="flush_email_outbox")
def flush_email_outbox(_task: object) -> dict[str, int]:
    """Deliver pending outbound emails from the durable outbox."""
    from server.services.email_sender import flush_outbox

    result = flush_outbox()
    logger.info(
        "Email outbox flush complete: sent=%s failed=%s expired=%s cleaned=%s",
        result.get("sent", 0),
        result.get("failed", 0),
        result.get("expired", 0),
        result.get("cleaned", 0),
    )
    return result


@task_decorator()
def requeue_expired_import_phases_task(_task: object) -> dict[str, object]:
    from server.immoapp_server.business_metrics_imports import record_import_status_signal
    from server.services.import_chunk_workflow import requeue_expired_import_phases
    from server.services.import_job_queue import dispatch_queued_imports

    result = requeue_expired_import_phases()
    dispatched = dispatch_queued_imports(limit=5, max_global_running=2)
    if int(result.get("requeued", 0) or 0) > 0:
        record_import_status_signal(
            event="phase_requeue",
            requeued_after_lease_expiry=True,
            count=int(result.get("requeued", 0) or 0),
        )
    payload: dict[str, object] = {**result, "dispatched": dispatched}
    logger.info("Import phase lease repair complete: %s", payload)
    return payload


@task_decorator()
def prune_importer_runtime_artifacts_task(
    _task: object,
    temp_ttl_hours: int = 12,
    failed_job_ttl_hours: int = 12,
) -> dict[str, object]:
    from server.services import import_runtime_maintenance
    from server.services.import_job_queue import dispatch_queued_imports

    temp_deleted = import_runtime_maintenance.prune_stale_temp_paths(
        temp_ttl_hours=max(1, int(temp_ttl_hours))
    )
    artifact_jobs_cleared = import_runtime_maintenance.prune_stale_artifact_jobs(
        failed_job_ttl_hours=max(1, int(failed_job_ttl_hours)),
        limit=100,
    )
    dispatched = dispatch_queued_imports(limit=5, max_global_running=2)
    payload: dict[str, object] = {
        "temp_dirs_deleted": temp_deleted,
        "artifact_jobs_cleared": artifact_jobs_cleared,
        "dispatched": dispatched,
    }
    logger.info("Importer runtime janitor complete: %s", payload)
    return payload


@task_decorator()
def repair_stalled_import_jobs_task(
    _task: object,
    _call_marker: object | None = None,
) -> dict[str, object]:
    from django.utils import timezone

    from server.api.task_registry import register_task
    from server.api.tasks_core import enqueue_import_task
    from server.api.tasks_import_review import import_review_submit_task
    from server.immoapp_server.business_metrics_imports import record_import_status_signal
    from server.imports.models import ImportJob
    from server.services.import_chunk_workflow import (
        request_workflow_cancellation,
        save_workflow_payload,
        workflow_payload,
    )
    from server.services.import_execution_health import execution_health_snapshot
    from server.services.import_job_queue import (
        dispatch_next_agency_import,
        dispatch_queued_imports,
        execution_owner_for_job,
        release_execution_slot,
    )
    from server.services.import_notifications import emit_import_notification
    from server.services.import_review_store import clear_db_review_state
    from server.services.import_review_submit_attempts import (
        request_review_submit_attempt_cancel,
    )
    from server.services.import_review_submit_dispatch import (
        REVIEW_SUBMIT_WORKFLOW_KEY,
        publish_review_submit_dispatch,
        review_submit_dispatch_payload,
    )
    from server.services.import_review_submit_service import (
        persist_review_submit_ready_state,
        review_submit_generic_error_payload,
    )
    from server.services.import_ui_summary import derive_terminal_result_state

    def _note_repair(job: ImportJob, *, reason: str) -> dict[str, Any]:
        payload = workflow_payload(job)
        payload["repair_attempted"] = True
        payload["repair_attempt_count"] = int(payload.get("repair_attempt_count", 0) or 0) + 1
        payload["repair_last_reason"] = str(reason or "")
        save_workflow_payload(job, payload)
        return payload

    def _fail_stalled_job(
        job: ImportJob,
        *,
        reason: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        payload = payload if payload is not None else _note_repair(job, reason=reason)
        request_workflow_cancellation(job=job)
        clear_db_review_state(job)
        payload["status"] = ImportJob.Status.FAILED
        payload["finished_at"] = timezone.now().isoformat()
        save_workflow_payload(job, payload)
        terminal_state = derive_terminal_result_state(
            status="failed",
            row_count=int((job.result_summary or {}).get("row_count", 0) or 0),
            created_count=int((job.result_summary or {}).get("created_count", 0) or 0),
            updated_count=int((job.result_summary or {}).get("updated_count", 0) or 0),
            skipped_count=int((job.result_summary or {}).get("skipped_count", 0) or 0),
            error_count=max(1, int((job.result_summary or {}).get("error_count", 0) or 0)),
            review_total_count=0,
            overflow_blocking=False,
            explicit_terminal_reason="failed",
        )
        progress_detail = dict(job.progress_detail or {})
        progress_detail.update(
            {
                "phase": "done",
                **terminal_state,
            }
        )
        result_summary = dict(job.result_summary or {})
        result_summary.update(
            {
                "success": False,
                **terminal_state,
            }
        )
        job.review_rows = []
        job.status = ImportJob.Status.FAILED
        job.stage = ImportJob.Stage.EXECUTION
        job.progress = 100
        job.error_message = message
        job.progress_detail = progress_detail
        job.result_summary = result_summary
        job.save(
            update_fields=[
                "review_rows",
                "status",
                "stage",
                "progress",
                "error_message",
                "progress_detail",
                "result_summary",
                "updated_at",
            ]
        )
        emit_import_notification(
            event_type="import.execution_failed",
            user_id=int(getattr(job, "user_id", 0) or 0),
            title="Import stalled and stopped",
            body=message,
            data={"session_id": str(job.id), "entity_type": str(job.detected_entity or "")},
        )

    def _wait_seconds(value: object) -> float:
        if isinstance(value, bool):
            return float(int(value))
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    scanned = 0
    stalled = 0
    queued = 0
    waiting_for_worker = 0
    review_submit_dispatch_waiting = 0
    repaired_queued = 0
    repaired_waiting = 0
    failed_waiting = 0
    repaired_review_submit_dispatch = 0
    failed_review_submit_dispatch = 0
    released_slots = 0
    repairs_attempted = 0
    for job in ImportJob.objects.filter(
        status__in=[ImportJob.Status.QUEUED, ImportJob.Status.RUNNING]
    ).order_by("created_at")[:100]:
        try:
            scanned += 1
            health = execution_health_snapshot(job)
            wait_state = str(health.get("wait_state", "") or "")
            stalled_reason = str(health.get("stalled_reason", "") or "")
            if bool(health.get("stalled", False)):
                stalled += 1
            if wait_state == "queued":
                queued += 1
            if wait_state == "waiting_for_worker":
                waiting_for_worker += 1
            if wait_state == "review_submit_dispatch":
                review_submit_dispatch_waiting += 1
            if not bool(health.get("stalled", False)):
                continue

            if wait_state == "queued" and stalled_reason == "queue_not_advancing":
                _note_repair(job, reason=stalled_reason)
                repairs_attempted += 1
                if dispatch_next_agency_import(agency_id=int(getattr(job, "agency_id", 0) or 0)):
                    repaired_queued += 1
                    record_import_status_signal(
                        event="watchdog_dispatch",
                        wait_state=wait_state,
                        stalled_reason=stalled_reason,
                        repair_attempted=True,
                        count=1,
                        wait_seconds=_wait_seconds(health.get("wait_seconds", 0)),
                    )
                continue

            if wait_state == "waiting_for_worker" and stalled_reason == "worker_not_picked_up":
                payload = _note_repair(job, reason=stalled_reason)
                repairs_attempted += 1
                repair_attempt_count = int(payload.get("repair_attempt_count", 0) or 0)
                if repair_attempt_count <= 1:
                    payload["status"] = ImportJob.Status.QUEUED
                    payload["queued_at"] = timezone.now().isoformat()
                    save_workflow_payload(job, payload)
                    progress_detail = dict(job.progress_detail or {})
                    progress_detail["phase"] = "queued"
                    job.status = ImportJob.Status.QUEUED
                    job.stage = ImportJob.Stage.EXECUTION
                    job.progress = 0
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
                    release_execution_slot(
                        agency_id=int(getattr(job, "agency_id", 0) or 0),
                        owner=execution_owner_for_job(job.id),
                    )
                    released_slots += 1
                    if dispatch_next_agency_import(
                        agency_id=int(getattr(job, "agency_id", 0) or 0)
                    ):
                        repaired_waiting += 1
                        record_import_status_signal(
                            event="watchdog_requeue",
                            wait_state=wait_state,
                            stalled_reason=stalled_reason,
                            repair_attempted=True,
                            count=1,
                            wait_seconds=_wait_seconds(health.get("wait_seconds", 0)),
                        )
                    continue

                _fail_stalled_job(
                    job,
                    reason=stalled_reason,
                    message=(
                        "We stopped this import because no worker picked it up after an automatic retry."
                    ),
                    payload=payload,
                )
                release_execution_slot(
                    agency_id=int(getattr(job, "agency_id", 0) or 0),
                    owner=execution_owner_for_job(job.id),
                )
                released_slots += 1
                failed_waiting += 1
                record_import_status_signal(
                    event="watchdog_fail",
                    terminal_reason="failed",
                    wait_state=wait_state,
                    stalled_reason=stalled_reason,
                    repair_attempted=True,
                    count=1,
                    wait_seconds=_wait_seconds(health.get("wait_seconds", 0)),
                )
                continue

            if (
                wait_state == "review_submit_dispatch"
                and stalled_reason == "review_submit_worker_stalled"
            ):
                dispatch_payload = review_submit_dispatch_payload(job)
                transition = request_review_submit_attempt_cancel(
                    job=job,
                    task_id=str(dispatch_payload.get("task_id", "") or job.task_id or ""),
                    reason=stalled_reason,
                    clear_workflow_keys=[REVIEW_SUBMIT_WORKFLOW_KEY],
                )
                if transition.changed:
                    job.refresh_from_db()
                    _note_repair(job, reason=stalled_reason)
                    repairs_attempted += 1
                    persist_review_submit_ready_state(
                        job=job,
                        error_payload=review_submit_generic_error_payload(),
                    )
                    repaired_review_submit_dispatch += 1
                    record_import_status_signal(
                        event="watchdog_cancel",
                        wait_state=wait_state,
                        stalled_reason=stalled_reason,
                        repair_attempted=True,
                        cancel_requested=True,
                        count=1,
                        wait_seconds=_wait_seconds(health.get("wait_seconds", 0)),
                    )
                else:
                    record_import_status_signal(
                        event="watchdog_observe",
                        wait_state=wait_state,
                        stalled_reason=stalled_reason,
                        repair_attempted=False,
                        count=1,
                        wait_seconds=_wait_seconds(health.get("wait_seconds", 0)),
                    )
                continue

            if wait_state == "review_submit_dispatch" and stalled_reason in {
                "review_submit_dispatch_pending",
                "review_submit_publish_failed",
                "review_submit_not_started",
            }:
                _note_repair(job, reason=stalled_reason)
                repairs_attempted += 1
                if publish_review_submit_dispatch(
                    job=job,
                    enqueue_review_submit_task_fn=lambda **kwargs: enqueue_import_task(
                        import_review_submit_task,
                        **kwargs,
                    ),
                    register_task_fn=register_task,
                ):
                    repaired_review_submit_dispatch += 1
                    record_import_status_signal(
                        event="watchdog_dispatch",
                        wait_state=wait_state,
                        stalled_reason=stalled_reason,
                        repair_attempted=True,
                        count=1,
                        wait_seconds=_wait_seconds(health.get("wait_seconds", 0)),
                    )
                else:
                    failed_review_submit_dispatch += 1
        except Exception:
            logger.exception(
                "Importer execution watchdog skipped job %s after an unexpected repair error",
                getattr(job, "id", None),
            )

    dispatched = dispatch_queued_imports(limit=5, max_global_running=2)
    result_payload: dict[str, object] = {
        "scanned": scanned,
        "stalled": stalled,
        "queued": queued,
        "waiting_for_worker": waiting_for_worker,
        "review_submit_dispatch": review_submit_dispatch_waiting,
        "repairs_attempted": repairs_attempted,
        "repaired_queued": repaired_queued,
        "repaired_waiting_for_worker": repaired_waiting,
        "failed_waiting_for_worker": failed_waiting,
        "repaired_review_submit_dispatch": repaired_review_submit_dispatch,
        "failed_review_submit_dispatch": failed_review_submit_dispatch,
        "released_slots": released_slots,
        "dispatched": dispatched,
    }
    logger.info("Importer execution watchdog complete: %s", result_payload)
    return result_payload


__all__ = [
    "expire_pending_registration_requests_task",
    "flush_email_outbox",
    "repair_stalled_import_jobs_task",
    "prune_importer_runtime_artifacts_task",
    "purge_old_audit_logs_task",
    "purge_old_auth_events_task",
    "purge_deleted_storage_objects_task",
    "purge_idempotency_records_task",
    "purge_pending_storage_objects_task",
    "requeue_expired_import_phases_task",
]
