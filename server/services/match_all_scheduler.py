"""Tenant-fair scheduler helpers for expensive /matches/*/all task triggers."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any, Literal, TypedDict

from celery.result import AsyncResult

from core.data import tenant_work_lease
from core.runtime.hub_runtime_profile import resolve_hub_runtime_profile
from core.utils.row_casts import row_int
from server.pg.uow import get_uow
from server.services import match_runtime_profile

ScheduleStatus = Literal["scheduled", "coalesced", "backpressure", "failed"]
ACTIVE_STATES: frozenset[str] = frozenset({"PENDING", "RECEIVED", "STARTED", "RETRY"})


class ScheduleResult(TypedDict):
    status: ScheduleStatus
    task_id: str | None
    state: str | None


def resolve_dynamic_max_in_flight(*, task_name: str, default_limit: int = 1) -> int:
    """Resolve per-tenant in-flight budget from current active-tenant pressure."""

    def _parse_env(name: str, default: int, *, min_v: int, max_v: int) -> int:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(min_v, min(max_v, value))

    floor = _parse_env(
        "IMMOAPP_MATCH_ALL_MIN_IN_FLIGHT",
        max(1, int(default_limit)),
        min_v=1,
        max_v=32,
    )
    cap = _parse_env("IMMOAPP_MATCH_ALL_MAX_IN_FLIGHT_CAP", 4, min_v=1, max_v=64)
    hub_limits = resolve_hub_runtime_profile().effective_limits()
    default_slots = max(1, hub_limits.max_background_jobs)
    global_slots = _parse_env(
        "IMMOAPP_MATCH_ALL_GLOBAL_SLOT_BUDGET",
        default_slots,
        min_v=1,
        max_v=128,
    )
    if floor >= cap:
        return floor
    try:
        with get_uow().session() as session:
            row = session.execute(
                """
                SELECT COUNT(DISTINCT agency_id) AS active_tenants
                FROM tenant_work_lease
                WHERE task_name = %s
                  AND in_flight > 0
                  AND lease_until IS NOT NULL
                  AND lease_until > NOW()
                """,
                (str(task_name),),
            ).fetchone()
        active_tenants = row_int(row, "active_tenants") if row else 0
    except Exception:
        return max(floor, min(cap, int(default_limit)))

    if active_tenants <= 0:
        computed = max(floor, min(cap, global_slots))
    else:
        computed = max(1, global_slots // active_tenants)
        computed = max(floor, min(cap, computed))
    profile = match_runtime_profile.effective_profile_state().profile
    computed = min(computed, hub_limits.max_background_jobs)
    if str(profile) == "red":
        return 1
    if str(profile) == "yellow":
        return max(1, computed // 2)
    return computed


def _reserve(
    *,
    task_name: str,
    stream_key: str,
    agency_id: int,
    provisional_owner: str,
    lease_seconds: int,
    max_in_flight: int,
) -> tuple[str | None, bool]:
    with get_uow().transaction() as session:
        return tenant_work_lease.reserve_stream_slot(
            session,
            task_name=task_name,
            agency_id=agency_id,
            stream_key=stream_key,
            provisional_owner=provisional_owner,
            lease_seconds=lease_seconds,
            max_in_flight=max_in_flight,
        )


def _release(
    *,
    task_name: str,
    stream_key: str,
    agency_id: int,
    lease_owner: str,
) -> None:
    with get_uow().transaction() as session:
        tenant_work_lease.release_stream_slot(
            session,
            task_name=task_name,
            agency_id=agency_id,
            stream_key=stream_key,
            lease_owner=lease_owner,
        )


def schedule_tenant_fair_task(
    *,
    task_name: str,
    stream_key: str,
    agency_id: int,
    lease_seconds: int,
    max_in_flight: int,
    launch_task: Callable[[], Any],
) -> ScheduleResult:
    """Schedule task with DB-backed per-tenant coalescing and backpressure."""

    normalized_agency_id = int(agency_id or 0)
    provisional_owner = f"pending-{uuid.uuid4()}"
    active_task_id, reserved = _reserve(
        task_name=task_name,
        stream_key=stream_key,
        agency_id=normalized_agency_id,
        provisional_owner=provisional_owner,
        lease_seconds=lease_seconds,
        max_in_flight=max_in_flight,
    )
    if active_task_id:
        state = str(AsyncResult(active_task_id).status)
        if state in ACTIVE_STATES:
            return {"status": "coalesced", "task_id": active_task_id, "state": state}
        _release(
            task_name=task_name,
            stream_key=stream_key,
            agency_id=normalized_agency_id,
            lease_owner=active_task_id,
        )
        active_task_id, reserved = _reserve(
            task_name=task_name,
            stream_key=stream_key,
            agency_id=normalized_agency_id,
            provisional_owner=provisional_owner,
            lease_seconds=lease_seconds,
            max_in_flight=max_in_flight,
        )
        if active_task_id:
            state = str(AsyncResult(active_task_id).status)
            return {"status": "coalesced", "task_id": active_task_id, "state": state}
    if not reserved:
        return {"status": "backpressure", "task_id": None, "state": None}

    task = launch_task()
    task_id = str(getattr(task, "id", "") or "").strip()
    if not task_id:
        _release(
            task_name=task_name,
            stream_key=stream_key,
            agency_id=normalized_agency_id,
            lease_owner=provisional_owner,
        )
        return {"status": "failed", "task_id": None, "state": None}
    with get_uow().transaction() as session:
        tenant_work_lease.assign_stream_owner(
            session,
            task_name=task_name,
            agency_id=normalized_agency_id,
            stream_key=stream_key,
            from_owner=provisional_owner,
            to_owner=task_id,
            lease_seconds=lease_seconds,
        )
    return {"status": "scheduled", "task_id": task_id, "state": None}


__all__ = [
    "schedule_tenant_fair_task",
    "resolve_dynamic_max_in_flight",
    "ACTIVE_STATES",
    "ScheduleResult",
    "ScheduleStatus",
]
