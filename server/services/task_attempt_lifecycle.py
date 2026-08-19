"""Domain-neutral task-attempt lifecycle decisions."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

ATTEMPT_PENDING = "pending"
ATTEMPT_PUBLISHED = "published"
ATTEMPT_PUBLISH_FAILED = "publish_failed"
ATTEMPT_STARTED = "started"
ATTEMPT_CANCEL_REQUESTED = "cancel_requested"
ATTEMPT_COMPLETED = "completed"
ATTEMPT_CONFLICT = "conflict"
ATTEMPT_FAILED = "failed"
ATTEMPT_CANCELLED = "cancelled"
ATTEMPT_STALE_IGNORED = "stale_ignored"

ATTEMPT_TERMINAL_STATUSES = frozenset(
    {
        ATTEMPT_COMPLETED,
        ATTEMPT_CONFLICT,
        ATTEMPT_FAILED,
        ATTEMPT_CANCELLED,
        ATTEMPT_STALE_IGNORED,
    }
)


class TaskAttemptStaleError(RuntimeError):
    """Raised when a worker no longer owns a durable task-attempt fence."""

    def __init__(self, *, attempt_type: str, task_id: str, status: str) -> None:
        super().__init__(
            f"Stale task attempt ignored: attempt_type={attempt_type} "
            f"task_id={task_id} status={status}"
        )
        self.attempt_type = str(attempt_type or "")
        self.task_id = str(task_id or "")
        self.status = str(status or "")


@dataclass(frozen=True)
class AttemptDecision:
    payload: dict[str, object]
    status: str
    changed: bool
    reason: str = ""


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _task_id_matches(payload: Mapping[str, object], task_id: str | None) -> bool:
    requested_task_id = str(task_id or "").strip()
    stored_task_id = str(payload.get("task_id", "") or "").strip()
    return not requested_task_id or requested_task_id == stored_task_id


def new_attempt_payload(
    *,
    attempt_type: str,
    task_id: str,
    now_iso: str,
    initial_payload: Mapping[str, object] | None = None,
    status: str = ATTEMPT_PENDING,
) -> dict[str, object]:
    payload = _mapping(initial_payload)
    payload["attempt_id"] = str(payload.get("attempt_id", "") or uuid.uuid4().hex)
    payload["attempt_type"] = str(attempt_type or "")
    payload["task_id"] = str(task_id or "")
    payload["status"] = str(status or ATTEMPT_PENDING)
    payload.setdefault("requested_at", now_iso)
    payload.setdefault("started_at", "")
    payload.setdefault("heartbeat_at", "")
    payload.setdefault("finished_at", "")
    payload.setdefault("cancel_requested_at", "")
    payload.setdefault("cancel_reason", "")
    return payload


def is_attempt_current(
    *,
    payload: Mapping[str, object],
    task_id: str | None,
    require_started: bool = True,
) -> AttemptDecision:
    status = str(payload.get("status", "") or "")
    if not _task_id_matches(payload, task_id):
        return AttemptDecision(
            payload=_mapping(payload),
            status=ATTEMPT_STALE_IGNORED,
            changed=False,
            reason="task_id_mismatch",
        )
    if status in ATTEMPT_TERMINAL_STATUSES | {ATTEMPT_CANCEL_REQUESTED}:
        return AttemptDecision(
            payload=_mapping(payload),
            status=status or ATTEMPT_STALE_IGNORED,
            changed=False,
            reason=status or ATTEMPT_STALE_IGNORED,
        )
    if require_started and status != ATTEMPT_STARTED:
        return AttemptDecision(
            payload=_mapping(payload),
            status=status or ATTEMPT_STALE_IGNORED,
            changed=False,
            reason=status or ATTEMPT_STALE_IGNORED,
        )
    return AttemptDecision(payload=_mapping(payload), status=status, changed=True)


def claim_started_payload(
    *,
    payload: Mapping[str, object],
    task_id: str | None,
    attempt_type: str,
    now_iso: str,
    startable_statuses: Iterable[str],
) -> AttemptDecision:
    payload_copy = _mapping(payload)
    stored_task_id = str(payload_copy.get("task_id", "") or "").strip()
    requested_task_id = str(task_id or "").strip()
    if not stored_task_id:
        return AttemptDecision(
            payload=payload_copy,
            status=ATTEMPT_STALE_IGNORED,
            changed=False,
            reason="missing_task_id",
        )
    if requested_task_id and requested_task_id != stored_task_id:
        return AttemptDecision(
            payload=payload_copy,
            status=ATTEMPT_STALE_IGNORED,
            changed=False,
            reason="task_id_mismatch",
        )
    current_status = str(payload_copy.get("status", "") or "")
    if current_status in ATTEMPT_TERMINAL_STATUSES | {
        ATTEMPT_STARTED,
        ATTEMPT_CANCEL_REQUESTED,
    }:
        return AttemptDecision(
            payload=payload_copy,
            status=ATTEMPT_STALE_IGNORED,
            changed=False,
            reason=current_status,
        )
    if current_status not in set(startable_statuses):
        return AttemptDecision(
            payload=payload_copy,
            status=ATTEMPT_STALE_IGNORED,
            changed=False,
            reason=current_status,
        )
    payload_copy["task_id"] = stored_task_id
    payload_copy["attempt_type"] = str(payload_copy.get("attempt_type", "") or attempt_type)
    payload_copy["attempt_id"] = str(payload_copy.get("attempt_id", "") or uuid.uuid4().hex)
    payload_copy["status"] = ATTEMPT_STARTED
    payload_copy["started_at"] = str(payload_copy.get("started_at", "") or now_iso)
    payload_copy["heartbeat_at"] = now_iso
    return AttemptDecision(payload=payload_copy, status=ATTEMPT_STARTED, changed=True)


def heartbeat_payload(
    *,
    payload: Mapping[str, object],
    task_id: str | None,
    now_iso: str,
) -> AttemptDecision:
    current = is_attempt_current(payload=payload, task_id=task_id)
    if not current.changed:
        return current
    payload_copy = _mapping(current.payload)
    payload_copy["heartbeat_at"] = now_iso
    return AttemptDecision(payload=payload_copy, status=ATTEMPT_STARTED, changed=True)


def cancel_payload(
    *,
    payload: Mapping[str, object],
    task_id: str | None,
    now_iso: str,
    reason: str,
    cancellable_statuses: Iterable[str] = (ATTEMPT_STARTED,),
) -> AttemptDecision:
    payload_copy = _mapping(payload)
    if not _task_id_matches(payload_copy, task_id):
        return AttemptDecision(
            payload=payload_copy,
            status=ATTEMPT_STALE_IGNORED,
            changed=False,
            reason="task_id_mismatch",
        )
    current_status = str(payload_copy.get("status", "") or "")
    if current_status in ATTEMPT_TERMINAL_STATUSES:
        return AttemptDecision(
            payload=payload_copy,
            status=current_status,
            changed=False,
            reason="terminal",
        )
    if current_status not in set(cancellable_statuses):
        return AttemptDecision(
            payload=payload_copy,
            status=current_status or ATTEMPT_STALE_IGNORED,
            changed=False,
            reason="not_cancellable",
        )
    payload_copy["status"] = ATTEMPT_CANCELLED
    payload_copy["cancel_requested_at"] = now_iso
    payload_copy["cancel_reason"] = str(reason or "")
    payload_copy["finished_at"] = now_iso
    return AttemptDecision(payload=payload_copy, status=ATTEMPT_CANCELLED, changed=True)


def finish_payload(
    *,
    payload: Mapping[str, object],
    task_id: str | None,
    attempt_type: str,
    requested_status: str,
    now_iso: str,
) -> AttemptDecision:
    payload_copy = _mapping(payload)
    status = str(requested_status or ATTEMPT_FAILED)
    if not _task_id_matches(payload_copy, task_id):
        return AttemptDecision(
            payload=payload_copy,
            status=ATTEMPT_STALE_IGNORED,
            changed=False,
            reason="task_id_mismatch",
        )
    current_status = str(payload_copy.get("status", "") or "")
    if current_status in ATTEMPT_TERMINAL_STATUSES:
        return AttemptDecision(
            payload=payload_copy,
            status=current_status,
            changed=False,
            reason=("terminal_conflict" if status != current_status else "terminal"),
        )
    payload_copy["attempt_type"] = str(payload_copy.get("attempt_type", "") or attempt_type)
    payload_copy["attempt_id"] = str(payload_copy.get("attempt_id", "") or uuid.uuid4().hex)
    payload_copy["status"] = status
    payload_copy["finished_at"] = now_iso
    return AttemptDecision(payload=payload_copy, status=status, changed=True)


__all__ = [
    "ATTEMPT_CANCELLED",
    "ATTEMPT_CANCEL_REQUESTED",
    "ATTEMPT_COMPLETED",
    "ATTEMPT_CONFLICT",
    "ATTEMPT_FAILED",
    "ATTEMPT_PENDING",
    "ATTEMPT_PUBLISHED",
    "ATTEMPT_PUBLISH_FAILED",
    "ATTEMPT_STARTED",
    "ATTEMPT_STALE_IGNORED",
    "ATTEMPT_TERMINAL_STATUSES",
    "AttemptDecision",
    "TaskAttemptStaleError",
    "cancel_payload",
    "claim_started_payload",
    "finish_payload",
    "heartbeat_payload",
    "is_attempt_current",
    "new_attempt_payload",
]
