"""Runtime governance helpers for import execution."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from core.runtime.hub_runtime_profile import resolve_hub_runtime_profile
from server.services import (
    match_runtime_profile,
    postgres_match_health,
    runtime_pressure_tripwire,
    work_admission,
)

PROFILE_GREEN = "green"
PROFILE_YELLOW = "yellow"
PROFILE_RED = "red"


@dataclass(frozen=True)
class ImportExecutionProfile:
    """Effective import execution runtime profile."""

    name: str
    chunk_rows: int
    duplicate_candidates: int
    worker_concurrency_hint: int


_PROFILE_SETTINGS: dict[str, ImportExecutionProfile] = {
    PROFILE_GREEN: ImportExecutionProfile(
        name=PROFILE_GREEN,
        chunk_rows=500,
        duplicate_candidates=5,
        worker_concurrency_hint=2,
    ),
    PROFILE_YELLOW: ImportExecutionProfile(
        name=PROFILE_YELLOW,
        chunk_rows=250,
        duplicate_candidates=3,
        worker_concurrency_hint=1,
    ),
    PROFILE_RED: ImportExecutionProfile(
        name=PROFILE_RED,
        chunk_rows=100,
        duplicate_candidates=2,
        worker_concurrency_hint=1,
    ),
}


def calculate_import_execution_cost(
    *,
    rows: int,
    entity_type: str,
    duplicate_strategy: str,
    smart_review_enabled: bool = True,
    bundle_mode: str = "single_entity",
    expected_review_ratio: float = 0.0,
) -> int:
    """Return the budget token cost for one import execution request."""

    safe_rows = max(0, int(rows))
    normalized_entity = str(entity_type or "").strip().lower()
    normalized_bundle = str(bundle_mode or "single_entity").strip().lower()
    normalized_strategy = str(duplicate_strategy or "").strip().lower()
    review_ratio = max(0.0, min(float(expected_review_ratio or 0.0), 1.0))

    entity_weight = 1.25 if normalized_entity in {"demande", "offer"} else 1.0
    bundle_weight = 1.5 if normalized_bundle == "same_side_bundle" else 1.0
    duplicate_weight = {
        "allow_all": 1.0,
        "skip": 1.1,
        "review": 1.25,
    }.get(normalized_strategy, 1.1)
    if not smart_review_enabled:
        review_weight = 1.0
    elif review_ratio > 0.30:
        review_weight = 1.30
    elif review_ratio > 0.10:
        review_weight = 1.15
    else:
        review_weight = 1.0
    effective_rows = (
        max(1.0, float(safe_rows))
        * entity_weight
        * bundle_weight
        * duplicate_weight
        * review_weight
    )
    return max(1, min(12, int(math.ceil(effective_rows / 1000.0))))


def effective_import_runtime_profile() -> ImportExecutionProfile:
    """
    Resolve the current import execution profile.

    Reuse the match runtime profile state as the shared DB-pressure signal source.
    """

    state = match_runtime_profile.effective_profile_state()
    profile_name = str(state.profile or PROFILE_YELLOW).strip().lower()
    profile = _PROFILE_SETTINGS.get(profile_name, _PROFILE_SETTINGS[PROFILE_YELLOW])
    hub_profile = resolve_hub_runtime_profile()
    hub_limits = hub_profile.effective_limits()
    return ImportExecutionProfile(
        name=profile.name,
        chunk_rows=min(profile.chunk_rows, hub_limits.import_batch_size),
        duplicate_candidates=profile.duplicate_candidates,
        worker_concurrency_hint=min(profile.worker_concurrency_hint, hub_limits.import_concurrency),
    )


def profile_aware_chunk_ceiling(current_ceiling: int) -> int:
    """Return an import chunk ceiling bounded by the current runtime profile."""

    profile = effective_import_runtime_profile()
    return max(1, min(int(current_ceiling), profile.chunk_rows))


def import_runtime_health_payload() -> dict[str, object]:
    """Return an admin-safe summary of import runtime governance state."""

    profile = effective_import_runtime_profile()
    profile_state = match_runtime_profile.effective_profile_state()
    snapshot = postgres_match_health.load_match_artifact_health_snapshot()
    payload: dict[str, object] = {
        "profile": profile.name,
        "hub_runtime_profile": resolve_hub_runtime_profile().profile_name,
        "chunk_rows": profile.chunk_rows,
        "duplicate_candidates": profile.duplicate_candidates,
        "worker_concurrency_hint": profile.worker_concurrency_hint,
        "reason": profile_state.reason,
        "sample_age_seconds": profile_state.sample_age_seconds,
        "stale": profile_state.stale,
        "runtime_sample_interval_seconds": work_admission.runtime_sample_interval_seconds(),
        "work_class_priorities": list(work_admission.WORK_CLASS_PRIORITY_ORDER),
        "degraded_limits": work_admission.degraded_limits_snapshot(),
        "active_work_counts": work_admission.active_work_counts(),
    }
    override = runtime_pressure_tripwire.current_override()
    if override is not None:
        payload["tripwire_override"] = {
            "profile": override.profile,
            "reason": override.reason,
            "created_at": override.created_at,
            "ttl_seconds": override.ttl_seconds,
        }
    if snapshot is not None:
        payload["db_pressure"] = {
            "active_connection_ratio": snapshot.db_snapshot.active_connection_ratio,
            "temp_bytes_delta_5m": snapshot.db_snapshot.temp_bytes_delta_5m,
            "statement_timeout_delta_5m": snapshot.db_snapshot.statement_timeout_delta_5m,
            "lock_timeout_delta_5m": snapshot.db_snapshot.lock_timeout_delta_5m,
        }
    return payload


def all_import_profiles() -> list[dict[str, object]]:
    """Return the locked import runtime profiles for diagnostics/tests."""

    return [asdict(profile) for profile in _PROFILE_SETTINGS.values()]
