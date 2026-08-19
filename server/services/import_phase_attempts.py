"""ImportChunkPhase-backed task-attempt fencing."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

from django.db import transaction
from django.utils import timezone

from server.imports.models import ImportChunkPhase, ImportJob
from server.services.import_workflow_leases import (
    StaleImportPhaseLeaseError,
    acquire_phase,
    complete_phase,
    fail_phase,
    heartbeat_phase_lease,
    phase_lease_active,
)
from server.services.import_workflow_storage import workflow_payload
from server.services.json_safe import json_safe_value
from server.services.task_attempt_lifecycle import ATTEMPT_CANCELLED

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class ImportPhaseAttemptCancelled(StaleImportPhaseLeaseError):
    """Raised when a current phase attempt observes cancellation before success."""


def assert_phase_attempt_current(*, phase: ImportChunkPhase) -> None:
    if not heartbeat_phase_lease(
        phase_id=int(phase.id),
        lease_token=str(phase.lease_token or ""),
    ):
        logger.info(
            "Stale importer phase attempt ignored",
            extra={
                "phase_id": int(phase.id),
                "attempt_type": str(phase.phase or ""),
                "attempt_id": str(phase.lease_token or ""),
                "task_id": str(phase.task_id or ""),
            },
        )
        raise StaleImportPhaseLeaseError(
            f"Chunk phase {phase.id} lost its lease before it could finish."
        )


def claim_phase_attempt_started(*, phase_id: int, task_id: str) -> ImportChunkPhase | None:
    phase = acquire_phase(phase_id=int(phase_id), task_id=str(task_id or ""))
    if phase is not None:
        logger.info(
            "Importer phase task attempt started",
            extra={
                "phase_id": int(phase.id),
                "attempt_type": str(phase.phase or ""),
                "attempt_id": str(phase.lease_token or ""),
                "task_id": str(phase.task_id or ""),
            },
        )
    return phase


def is_phase_attempt_current(
    *,
    phase_id: int,
    attempt_id: str = "",
    lease_token: str = "",
) -> bool:
    current_attempt_id = str(attempt_id or lease_token or "")
    return phase_lease_active(phase_id=int(phase_id), lease_token=current_attempt_id)


def complete_phase_attempt(
    *,
    phase_id: int,
    attempt_id: str,
    metrics_payload: dict[str, Any] | None = None,
) -> bool:
    completed = complete_phase(
        phase_id=int(phase_id),
        lease_token=str(attempt_id or ""),
        metrics_payload=metrics_payload,
    )
    if completed:
        logger.info(
            "Importer phase task attempt terminal transition accepted",
            extra={
                "phase_id": int(phase_id),
                "attempt_id": str(attempt_id or ""),
                "status": "completed",
            },
        )
    return completed


def fail_phase_attempt(
    *,
    phase_id: int,
    attempt_id: str,
    error_payload: dict[str, Any],
) -> bool:
    failed = fail_phase(
        phase_id=int(phase_id),
        lease_token=str(attempt_id or ""),
        error_payload=error_payload,
    )
    if failed:
        logger.info(
            "Importer phase task attempt terminal transition accepted",
            extra={
                "phase_id": int(phase_id),
                "attempt_id": str(attempt_id or ""),
                "status": "failed",
            },
        )
    return failed


def cancel_phase_attempt(
    *,
    phase_id: int,
    attempt_id: str,
    error_payload: dict[str, Any] | None = None,
) -> bool:
    with transaction.atomic():
        phase = ImportChunkPhase.objects.select_for_update().filter(id=int(phase_id)).first()
        if (
            phase is None
            or phase.status != ImportChunkPhase.Status.RUNNING
            or str(phase.lease_token or "") != str(attempt_id or "")
        ):
            return False
        phase.status = ImportChunkPhase.Status.CANCELLED
        phase.error_payload = cast(dict[str, Any], json_safe_value(dict(error_payload or {})))
        phase.lease_token = ""
        phase.heartbeat_at = None
        phase.lease_expires_at = None
        phase.finished_at = timezone.now()
        phase.save(
            update_fields=[
                "status",
                "error_payload",
                "lease_token",
                "heartbeat_at",
                "lease_expires_at",
                "finished_at",
                "updated_at",
            ]
        )
    logger.info(
        "Importer phase task attempt cancellation accepted",
        extra={
            "phase_id": int(phase_id),
            "attempt_id": str(attempt_id or ""),
            "status": ATTEMPT_CANCELLED,
        },
    )
    return True


def raise_phase_attempt_cancelled(*, phase: ImportChunkPhase, reason: str) -> None:
    logger.info(
        "Importer phase task attempt observed cancellation",
        extra={
            "phase_id": int(phase.id),
            "attempt_type": str(phase.phase or ""),
            "attempt_id": str(phase.lease_token or ""),
            "task_id": str(phase.task_id or ""),
            "cancel_reason": str(reason or ""),
        },
    )
    raise ImportPhaseAttemptCancelled(
        f"Chunk phase {phase.id} was cancelled before {reason or 'success'}."
    )


def run_with_phase_attempt_fence(
    *,
    phase: ImportChunkPhase,
    operation: str,
    fn: Callable[[], _T],
) -> _T:
    """Run a phase write while ordering cancellation against the phase lease row."""

    assert_phase_attempt_current(phase=phase)
    with transaction.atomic():
        locked_phase = (
            ImportChunkPhase.objects.select_for_update()
            .select_related("chunk", "chunk__job")
            .get(id=phase.id)
        )
        job = cast(ImportJob, locked_phase.chunk.job)
        payload = workflow_payload(job)
        if (
            locked_phase.status != ImportChunkPhase.Status.RUNNING
            or str(locked_phase.lease_token or "") != str(phase.lease_token or "")
            or job.status != ImportJob.Status.RUNNING
        ):
            logger.info(
                "Importer phase attempt fenced write ignored",
                extra={
                    "phase_id": int(phase.id),
                    "attempt_type": str(phase.phase or ""),
                    "attempt_id": str(phase.lease_token or ""),
                    "task_id": str(phase.task_id or ""),
                    "operation": str(operation or ""),
                },
            )
            raise StaleImportPhaseLeaseError(
                f"Chunk phase {phase.id} lost its lease before {operation or 'a write'}."
            )
        if bool(payload.get("cancel_requested", False)):
            raise_phase_attempt_cancelled(phase=phase, reason=operation or "a write")
        return fn()


__all__ = [
    "ImportPhaseAttemptCancelled",
    "StaleImportPhaseLeaseError",
    "assert_phase_attempt_current",
    "cancel_phase_attempt",
    "claim_phase_attempt_started",
    "complete_phase_attempt",
    "fail_phase_attempt",
    "is_phase_attempt_current",
    "raise_phase_attempt_cancelled",
    "run_with_phase_attempt_fence",
]
