from __future__ import annotations

from server.services.task_attempt_lifecycle import (
    ATTEMPT_CANCELLED,
    ATTEMPT_COMPLETED,
    ATTEMPT_FAILED,
    ATTEMPT_PENDING,
    ATTEMPT_PUBLISHED,
    ATTEMPT_STALE_IGNORED,
    ATTEMPT_STARTED,
    cancel_payload,
    claim_started_payload,
    finish_payload,
    heartbeat_payload,
    new_attempt_payload,
)


def test_attempt_lifecycle_allows_pending_started_completed() -> None:
    payload = new_attempt_payload(
        attempt_type="unit",
        task_id="task-1",
        now_iso="2026-04-11T10:00:00+00:00",
        status=ATTEMPT_PENDING,
    )

    started = claim_started_payload(
        payload=payload,
        task_id="task-1",
        attempt_type="unit",
        now_iso="2026-04-11T10:00:01+00:00",
        startable_statuses={ATTEMPT_PENDING},
    )
    completed = finish_payload(
        payload=started.payload,
        task_id="task-1",
        attempt_type="unit",
        requested_status=ATTEMPT_COMPLETED,
        now_iso="2026-04-11T10:00:02+00:00",
    )

    assert started.changed is True
    assert started.status == ATTEMPT_STARTED
    assert completed.changed is True
    assert completed.status == ATTEMPT_COMPLETED


def test_attempt_task_id_mismatch_is_stale_noop() -> None:
    payload = new_attempt_payload(
        attempt_type="unit",
        task_id="task-1",
        now_iso="2026-04-11T10:00:00+00:00",
        status=ATTEMPT_PUBLISHED,
    )

    decision = claim_started_payload(
        payload=payload,
        task_id="task-2",
        attempt_type="unit",
        now_iso="2026-04-11T10:00:01+00:00",
        startable_statuses={ATTEMPT_PUBLISHED},
    )

    assert decision.changed is False
    assert decision.status == ATTEMPT_STALE_IGNORED
    assert decision.reason == "task_id_mismatch"
    assert decision.payload == payload


def test_attempt_terminal_status_is_monotonic() -> None:
    started = {
        "attempt_type": "unit",
        "task_id": "task-1",
        "status": ATTEMPT_STARTED,
    }
    completed = finish_payload(
        payload=started,
        task_id="task-1",
        attempt_type="unit",
        requested_status=ATTEMPT_COMPLETED,
        now_iso="2026-04-11T10:00:01+00:00",
    )
    failed_over_completed = finish_payload(
        payload=completed.payload,
        task_id="task-1",
        attempt_type="unit",
        requested_status=ATTEMPT_FAILED,
        now_iso="2026-04-11T10:00:02+00:00",
    )
    failed = finish_payload(
        payload=started,
        task_id="task-1",
        attempt_type="unit",
        requested_status=ATTEMPT_FAILED,
        now_iso="2026-04-11T10:00:01+00:00",
    )
    completed_over_failed = finish_payload(
        payload=failed.payload,
        task_id="task-1",
        attempt_type="unit",
        requested_status=ATTEMPT_COMPLETED,
        now_iso="2026-04-11T10:00:02+00:00",
    )

    assert failed_over_completed.changed is False
    assert failed_over_completed.status == ATTEMPT_COMPLETED
    assert failed_over_completed.reason == "terminal_conflict"
    assert completed_over_failed.changed is False
    assert completed_over_failed.status == ATTEMPT_FAILED
    assert completed_over_failed.reason == "terminal_conflict"


def test_attempt_cancellation_only_applies_to_explicit_cancellable_states() -> None:
    started = {
        "attempt_type": "unit",
        "task_id": "task-1",
        "status": ATTEMPT_STARTED,
    }
    pending = {
        "attempt_type": "unit",
        "task_id": "task-1",
        "status": ATTEMPT_PENDING,
    }

    cancelled = cancel_payload(
        payload=started,
        task_id="task-1",
        now_iso="2026-04-11T10:00:01+00:00",
        reason="watchdog",
        cancellable_statuses={ATTEMPT_STARTED},
    )
    rejected = cancel_payload(
        payload=pending,
        task_id="task-1",
        now_iso="2026-04-11T10:00:01+00:00",
        reason="watchdog",
        cancellable_statuses={ATTEMPT_STARTED},
    )

    assert cancelled.changed is True
    assert cancelled.status == ATTEMPT_CANCELLED
    assert rejected.changed is False
    assert rejected.status == ATTEMPT_PENDING
    assert rejected.reason == "not_cancellable"


def test_attempt_heartbeat_does_not_mutate_terminal_status() -> None:
    payload = {
        "attempt_type": "unit",
        "task_id": "task-1",
        "status": ATTEMPT_COMPLETED,
        "heartbeat_at": "2026-04-11T10:00:00+00:00",
    }

    decision = heartbeat_payload(
        payload=payload,
        task_id="task-1",
        now_iso="2026-04-11T10:00:01+00:00",
    )

    assert decision.changed is False
    assert decision.status == ATTEMPT_COMPLETED
    assert decision.payload == payload
