"""Execution-health diagnostics for importer status and watchdogs."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from server.imports.models import ImportChunkPhase, ImportJob
from server.services.import_chunk_workflow import workflow_payload
from server.services.import_review_submit_dispatch import (
    REVIEW_SUBMIT_DISPATCH_PENDING,
    REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED,
    REVIEW_SUBMIT_DISPATCH_PUBLISHED,
    REVIEW_SUBMIT_DISPATCH_STARTED,
    review_submit_dispatch_payload,
)

_WAITING_FOR_WORKER_STALL_SECONDS = 60
_QUEUED_STALL_SECONDS = 120


def _parse_datetimeish(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _seconds_since(value: datetime | None, *, now: datetime) -> int:
    if value is None:
        return 0
    delta = now - value
    return max(0, int(delta.total_seconds()))


def execution_health_snapshot(job: ImportJob) -> dict[str, object]:
    now = timezone.now()
    payload = workflow_payload(job)
    review_submit_dispatch = review_submit_dispatch_payload(job)
    review_submit_dispatch_status = str(review_submit_dispatch.get("status", "") or "")
    queued_at = _parse_datetimeish(payload.get("queued_at"))
    started_at = _parse_datetimeish(payload.get("started_at"))
    progress_detail = dict(job.progress_detail or {})
    phases = list(
        ImportChunkPhase.objects.filter(chunk__job=job).order_by(
            "-started_at",
            "-heartbeat_at",
            "-created_at",
            "-id",
        )[:20]
    )
    active_phase = next(
        (phase for phase in phases if phase.status == ImportChunkPhase.Status.RUNNING),
        None,
    )
    last_phase_started_at = next((phase.started_at for phase in phases if phase.started_at), None)
    last_phase_heartbeat_at = next(
        (phase.heartbeat_at for phase in phases if phase.heartbeat_at),
        None,
    )
    phase_hint = str(progress_detail.get("phase", "") or "").strip().lower()
    wait_state = "running"
    wait_reason = "phase_running"
    wait_seconds = 0
    if (
        job.status == ImportJob.Status.RUNNING
        and job.stage == ImportJob.Stage.REVIEW
        and review_submit_dispatch_status
        in {
            REVIEW_SUBMIT_DISPATCH_PENDING,
            REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED,
            REVIEW_SUBMIT_DISPATCH_PUBLISHED,
            REVIEW_SUBMIT_DISPATCH_STARTED,
        }
    ):
        wait_state = "review_submit_dispatch"
        if review_submit_dispatch_status == REVIEW_SUBMIT_DISPATCH_PENDING:
            wait_reason = "dispatch_pending"
            wait_seconds = _seconds_since(
                _parse_datetimeish(review_submit_dispatch.get("requested_at")) or job.updated_at,
                now=now,
            )
        elif review_submit_dispatch_status == REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED:
            wait_reason = "publish_failed"
            wait_seconds = _seconds_since(
                _parse_datetimeish(review_submit_dispatch.get("last_attempted_at"))
                or _parse_datetimeish(review_submit_dispatch.get("requested_at"))
                or job.updated_at,
                now=now,
            )
        elif review_submit_dispatch_status == REVIEW_SUBMIT_DISPATCH_STARTED:
            wait_reason = "worker_running"
            wait_seconds = _seconds_since(
                _parse_datetimeish(review_submit_dispatch.get("heartbeat_at"))
                or _parse_datetimeish(review_submit_dispatch.get("started_at"))
                or _parse_datetimeish(review_submit_dispatch.get("published_at"))
                or job.updated_at,
                now=now,
            )
        else:
            wait_reason = "worker_pickup"
            wait_seconds = _seconds_since(
                _parse_datetimeish(review_submit_dispatch.get("published_at")) or job.updated_at,
                now=now,
            )
    elif job.status == ImportJob.Status.QUEUED:
        wait_state = "queued"
        wait_reason = "agency_queue"
        wait_seconds = _seconds_since(queued_at or job.updated_at, now=now)
    elif job.status == ImportJob.Status.RUNNING and (
        active_phase is None
        and last_phase_started_at is None
        and phase_hint in {"", "queued", "executing"}
    ):
        wait_state = "waiting_for_worker"
        wait_reason = "worker_pickup"
        wait_seconds = _seconds_since(started_at or job.updated_at, now=now)
    elif job.status == ImportJob.Status.RUNNING:
        wait_state = "running"
        wait_reason = "phase_running"
        wait_seconds = _seconds_since(
            active_phase.started_at if active_phase is not None else started_at or job.updated_at,
            now=now,
        )
    elif job.stage == ImportJob.Stage.REVIEW:
        wait_state = "review"
    elif job.status == ImportJob.Status.COMPLETED:
        wait_state = "completed"
    elif job.status == ImportJob.Status.FAILED:
        wait_state = "failed"

    stalled = False
    stalled_reason = ""
    if wait_state == "review_submit_dispatch" and wait_seconds >= _WAITING_FOR_WORKER_STALL_SECONDS:
        stalled = True
        if wait_reason == "dispatch_pending":
            stalled_reason = "review_submit_dispatch_pending"
        elif wait_reason == "publish_failed":
            stalled_reason = "review_submit_publish_failed"
        elif wait_reason == "worker_running":
            stalled_reason = "review_submit_worker_stalled"
        else:
            stalled_reason = "review_submit_not_started"
    elif wait_state == "waiting_for_worker" and wait_seconds >= _WAITING_FOR_WORKER_STALL_SECONDS:
        stalled = True
        stalled_reason = "worker_not_picked_up"
    elif wait_state == "queued" and wait_seconds >= _QUEUED_STALL_SECONDS:
        other_running_exists = (
            ImportJob.objects.filter(
                agency_id=int(getattr(job, "agency_id", 0) or 0),
                status=ImportJob.Status.RUNNING,
            )
            .exclude(id=job.id)
            .exists()
        )
        if not other_running_exists:
            stalled = True
            stalled_reason = "queue_not_advancing"
    elif wait_state == "running" and active_phase is not None:
        lease_expired = (
            active_phase.lease_expires_at is not None and active_phase.lease_expires_at < now
        )
        heartbeat_stale = (
            active_phase.heartbeat_at is not None
            and _seconds_since(active_phase.heartbeat_at, now=now)
            >= _WAITING_FOR_WORKER_STALL_SECONDS
        )
        if lease_expired or heartbeat_stale:
            stalled = True
            stalled_reason = "phase_heartbeat_expired"

    return {
        "queued_at": _isoformat(queued_at),
        "started_at": _isoformat(started_at),
        "last_phase_started_at": _isoformat(last_phase_started_at),
        "last_phase_heartbeat_at": _isoformat(last_phase_heartbeat_at),
        "wait_state": wait_state,
        "wait_reason": (
            wait_reason
            if wait_state in {"queued", "waiting_for_worker", "running", "review_submit_dispatch"}
            else ""
        ),
        "wait_seconds": int(wait_seconds or 0),
        "stalled": bool(stalled),
        "stalled_reason": stalled_reason,
        "can_cancel": job.status in {ImportJob.Status.QUEUED, ImportJob.Status.RUNNING},
        "can_close": True,
        "repair_attempted": bool(payload.get("repair_attempted", False)),
        "repair_attempt_count": int(payload.get("repair_attempt_count", 0) or 0),
        "repair_last_reason": str(payload.get("repair_last_reason", "") or ""),
    }


__all__ = ["execution_health_snapshot"]
