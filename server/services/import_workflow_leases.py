"""Lease and cancellation helpers for distributed importer execution."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Any, cast

from django.db import transaction
from django.utils import timezone

from server.imports.models import ImportChunkPhase, ImportJob
from server.services.import_workflow_storage import _save_workflow_payload, workflow_payload
from server.services.json_safe import json_safe_value


def _phase_lease_ttl_seconds() -> int:
    raw_value = (os.environ.get("IMMOAPP_IMPORT_PHASE_LEASE_TTL_SECONDS") or "").strip()
    try:
        ttl_value = int(raw_value)
    except ValueError:
        ttl_value = 180
    return max(30, min(ttl_value, 3600))


class StaleImportPhaseLeaseError(RuntimeError):
    """Raised when a chunk task loses ownership of its phase lease."""


def acquire_phase(
    *,
    phase_id: int,
    task_id: str,
) -> ImportChunkPhase | None:
    with transaction.atomic():
        phase = (
            ImportChunkPhase.objects.select_for_update()
            .select_related("chunk", "chunk__job", "chunk__job__user")
            .get(id=phase_id)
        )
        job = cast(ImportJob, phase.chunk.job)
        payload = workflow_payload(job)
        if job.status != ImportJob.Status.RUNNING or bool(payload.get("cancel_requested", False)):
            if phase.status in {
                ImportChunkPhase.Status.BLOCKED,
                ImportChunkPhase.Status.PENDING,
                ImportChunkPhase.Status.QUEUED,
            }:
                phase.status = ImportChunkPhase.Status.CANCELLED
                phase.finished_at = timezone.now()
                phase.save(update_fields=["status", "finished_at", "updated_at"])
            return None
        if phase.status in {
            ImportChunkPhase.Status.COMPLETED,
            ImportChunkPhase.Status.BLOCKED,
            ImportChunkPhase.Status.CANCELLED,
        }:
            return None
        if phase.status == ImportChunkPhase.Status.RUNNING and str(phase.task_id or "") != task_id:
            return None
        now = timezone.now()
        phase.status = ImportChunkPhase.Status.RUNNING
        phase.attempt_count = int(phase.attempt_count or 0) + 1
        phase.task_id = str(task_id or "")
        phase.lease_token = uuid.uuid4().hex
        phase.heartbeat_at = now
        phase.lease_expires_at = now + timedelta(seconds=_phase_lease_ttl_seconds())
        phase.started_at = now
        phase.error_payload = {}
        phase.save(
            update_fields=[
                "status",
                "attempt_count",
                "task_id",
                "lease_token",
                "heartbeat_at",
                "lease_expires_at",
                "started_at",
                "error_payload",
                "updated_at",
            ]
        )
        return cast(ImportChunkPhase, phase)


def heartbeat_phase_lease(*, phase_id: int, lease_token: str) -> bool:
    if not lease_token:
        return False
    updated = ImportChunkPhase.objects.filter(
        id=phase_id,
        status=ImportChunkPhase.Status.RUNNING,
        lease_token=str(lease_token),
    ).update(
        heartbeat_at=timezone.now(),
        lease_expires_at=timezone.now() + timedelta(seconds=_phase_lease_ttl_seconds()),
        updated_at=timezone.now(),
    )
    return bool(updated)


def phase_lease_active(*, phase_id: int, lease_token: str) -> bool:
    if not lease_token:
        return False
    return bool(
        ImportChunkPhase.objects.filter(
            id=phase_id,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token=str(lease_token),
        ).exists()
    )


def complete_phase(
    *,
    phase_id: int,
    lease_token: str = "",
    metrics_payload: dict[str, Any] | None = None,
) -> bool:
    updated = ImportChunkPhase.objects.filter(
        id=phase_id,
        status=ImportChunkPhase.Status.RUNNING,
        lease_token=str(lease_token or ""),
    ).update(
        status=ImportChunkPhase.Status.COMPLETED,
        metrics_payload=cast(dict[str, Any], json_safe_value(dict(metrics_payload or {}))),
        error_payload=cast(dict[str, Any], json_safe_value({})),
        lease_token="",
        heartbeat_at=None,
        lease_expires_at=None,
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )
    return bool(updated)


def fail_phase(
    *,
    phase_id: int,
    lease_token: str = "",
    error_payload: dict[str, Any],
) -> bool:
    updated = ImportChunkPhase.objects.filter(
        id=phase_id,
        status=ImportChunkPhase.Status.RUNNING,
        lease_token=str(lease_token or ""),
    ).update(
        status=ImportChunkPhase.Status.FAILED,
        error_payload=cast(dict[str, Any], json_safe_value(dict(error_payload))),
        lease_token="",
        heartbeat_at=None,
        lease_expires_at=None,
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )
    return bool(updated)


def cancel_pending_phases(*, job: ImportJob) -> int:
    return int(
        ImportChunkPhase.objects.filter(
            chunk__job=job,
            status__in=[
                ImportChunkPhase.Status.BLOCKED,
                ImportChunkPhase.Status.PENDING,
                ImportChunkPhase.Status.QUEUED,
            ],
        ).update(
            status=ImportChunkPhase.Status.CANCELLED,
            lease_token="",
            heartbeat_at=None,
            lease_expires_at=None,
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
    )


def request_workflow_cancellation(*, job: ImportJob) -> int:
    with transaction.atomic():
        locked_job = ImportJob.objects.select_for_update().get(id=job.id)
        payload = workflow_payload(locked_job)
        payload["cancel_requested"] = True
        _save_workflow_payload(locked_job, payload)
        updated_state = getattr(locked_job, "workflow_state", None)
        if updated_state is not None:
            cast(Any, job).workflow_state = updated_state
        job.result_summary = locked_job.result_summary
        return cancel_pending_phases(job=locked_job)


def requeue_expired_import_phases() -> dict[str, int]:
    now = timezone.now()
    phases = list(
        ImportChunkPhase.objects.select_related("chunk", "chunk__job")
        .filter(
            status=ImportChunkPhase.Status.RUNNING,
            lease_expires_at__isnull=False,
            lease_expires_at__lt=now,
        )
        .order_by("id")
    )
    requeued = 0
    cancelled = 0
    for phase in phases:
        job = cast(ImportJob, phase.chunk.job)
        payload = workflow_payload(job)
        metrics = dict(phase.metrics_payload or {})
        if job.status == ImportJob.Status.RUNNING and not bool(
            payload.get("cancel_requested", False)
        ):
            metrics["requeued_after_lease_expiry"] = True
            ImportChunkPhase.objects.filter(id=phase.id).update(
                status=ImportChunkPhase.Status.QUEUED,
                lease_token="",
                heartbeat_at=None,
                lease_expires_at=None,
                metrics_payload=cast(dict[str, Any], json_safe_value(metrics)),
                updated_at=timezone.now(),
            )
            requeued += 1
        else:
            ImportChunkPhase.objects.filter(id=phase.id).update(
                status=ImportChunkPhase.Status.CANCELLED,
                lease_token="",
                heartbeat_at=None,
                lease_expires_at=None,
                finished_at=timezone.now(),
                updated_at=timezone.now(),
            )
            cancelled += 1
    return {"requeued": requeued, "cancelled": cancelled}


__all__ = [
    "StaleImportPhaseLeaseError",
    "acquire_phase",
    "cancel_pending_phases",
    "complete_phase",
    "fail_phase",
    "heartbeat_phase_lease",
    "phase_lease_active",
    "request_workflow_cancellation",
    "requeue_expired_import_phases",
]
