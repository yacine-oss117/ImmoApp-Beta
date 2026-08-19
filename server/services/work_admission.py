"""Shared work-class visibility helpers for expensive control-plane tasks."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from core.utils.row_casts import row_int
from server.pg.uow import get_uow
from server.services import match_runtime_profile, tenant_resource_governor

logger = logging.getLogger(__name__)

BackgroundWorkClass = Literal[
    "import_parse",
    "import_plan",
    "import_load",
    "import_finalize",
    "match_all",
    "match_rebuild_batch",
    "cache_rebuild",
    "maintenance_repair",
]

AdmissionMode = Literal["normal", "degraded", "queued", "rejected"]

WORK_CLASS_PRIORITY_ORDER: tuple[BackgroundWorkClass, ...] = (
    "import_load",
    "match_all",
    "match_rebuild_batch",
    "import_plan",
    "import_parse",
    "import_finalize",
    "maintenance_repair",
)


@dataclass(frozen=True)
class WorkAdmissionDecision:
    allowed: bool
    retry_after: int
    degraded: bool
    runtime_profile: str
    admission_mode: AdmissionMode
    pressure_reason: str
    fair_share_limit: int = 0


def _env_int(name: str, default: int, *, floor: int, ceiling: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(floor, min(value, ceiling))


def active_work_counts() -> dict[str, int]:
    counts: dict[str, int] = {
        "import_parse": 0,
        "import_plan": 0,
        "import_load": 0,
        "import_finalize": 0,
        "match_all": 0,
        "match_rebuild_batch": 0,
        "cache_rebuild": 0,
        "maintenance_repair": 0,
    }
    try:
        with get_uow().session() as session:
            import_parse_row = session.execute(
                """
                SELECT COUNT(*) AS count
                FROM imports_importjob
                WHERE status = %s
                """,
                ("parsing",),
            ).fetchone()
            import_finalize_row = session.execute(
                """
                SELECT COUNT(*) AS count
                FROM imports_importjob
                WHERE status = %s
                  AND progress = 100
                """,
                ("running",),
            ).fetchone()
            import_plan_row = session.execute(
                """
                SELECT COUNT(*) AS count
                FROM imports_importchunkphase
                WHERE phase = %s
                  AND status = %s
                """,
                ("plan", "running"),
            ).fetchone()
            import_load_row = session.execute(
                """
                SELECT COUNT(*) AS count
                FROM imports_importchunkphase
                WHERE phase = %s
                  AND status = %s
                """,
                ("load", "running"),
            ).fetchone()
            match_row = session.execute(
                """
                SELECT COALESCE(SUM(in_flight), 0) AS count
                FROM tenant_work_lease
                WHERE task_name = %s
                  AND lease_until IS NOT NULL
                  AND lease_until > NOW()
                """,
                ("matches_all",),
            ).fetchone()
            rebuild_row = session.execute(
                """
                SELECT COUNT(*) AS count
                FROM match_rebuild_state
                WHERE scope = 'demande'
                  AND pending = TRUE
                  AND dispatch_claim_expires_at IS NOT NULL
                  AND dispatch_claim_expires_at > NOW()
                """,
                (),
            ).fetchone()
            if import_parse_row:
                counts["import_parse"] = row_int(import_parse_row, "count")
            if import_finalize_row:
                counts["import_finalize"] = row_int(import_finalize_row, "count")
            if import_plan_row:
                counts["import_plan"] = row_int(import_plan_row, "count")
            if import_load_row:
                counts["import_load"] = row_int(import_load_row, "count")
            if match_row:
                counts["match_all"] = row_int(match_row, "count")
            if rebuild_row:
                counts["match_rebuild_batch"] = row_int(rebuild_row, "count")
    except Exception:
        logger.exception("Failed to read active work counts; using degraded pressure signal.")
        counts["degraded"] = 1
    return counts


def any_active_expensive_work() -> bool:
    counts = active_work_counts()
    if int(counts.get("degraded", 0) or 0) > 0:
        return True
    return any(value > 0 for value in counts.values())


def runtime_sample_interval_seconds() -> int:
    if any_active_expensive_work():
        return _env_int(
            "IMMOAPP_MATCH_HEALTH_SAMPLE_INTERVAL_ACTIVE_SECONDS",
            5,
            floor=2,
            ceiling=60,
        )
    return _env_int(
        "IMMOAPP_MATCH_HEALTH_SAMPLE_INTERVAL_IDLE_SECONDS",
        30,
        floor=5,
        ceiling=300,
    )


def degraded_limits_snapshot() -> dict[str, int]:
    return {
        "import_load_global_max": 2,
        "import_parse_global_max": 2,
        "match_all_global_max": 2,
        "agency_import_running_max": 1,
        "agency_import_queued_max": 1,
    }


def admit_match_all(
    *,
    agency_id: int,
    task_name: str,
    default_limit: int = 1,
    retry_after_seconds: int = 10,
) -> WorkAdmissionDecision:
    from server.services import match_all_scheduler

    fair_share_limit = max(
        1,
        int(
            match_all_scheduler.resolve_dynamic_max_in_flight(
                task_name=task_name,
                default_limit=default_limit,
            )
        ),
    )
    profile_state = match_runtime_profile.effective_profile_state()
    if tenant_resource_governor.governor_backend_available():
        allowed, retry_after = tenant_resource_governor.allow_expensive_work(
            budget_name="match_all",
            agency_id=int(agency_id),
        )
        return WorkAdmissionDecision(
            allowed=bool(allowed),
            retry_after=int(retry_after or 0),
            degraded=False,
            runtime_profile=str(profile_state.profile or "yellow"),
            admission_mode="normal",
            pressure_reason="token_bucket",
            fair_share_limit=fair_share_limit,
        )
    counts = active_work_counts()
    degraded_pressure = int(counts.get("degraded", 0) or 0) > 0
    allowed = not degraded_pressure and int(counts.get("match_all", 0) or 0) < 2
    return WorkAdmissionDecision(
        allowed=allowed,
        retry_after=0 if allowed else max(1, int(retry_after_seconds)),
        degraded=True,
        runtime_profile="red",
        admission_mode="degraded",
        pressure_reason="degraded_match_all_fallback",
        fair_share_limit=1,
    )


__all__ = [
    "AdmissionMode",
    "BackgroundWorkClass",
    "WorkAdmissionDecision",
    "WORK_CLASS_PRIORITY_ORDER",
    "active_work_counts",
    "admit_match_all",
    "degraded_limits_snapshot",
    "any_active_expensive_work",
    "runtime_sample_interval_seconds",
]
