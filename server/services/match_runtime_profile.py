"""Adaptive runtime profile controller for match rebuild tasks."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from django.core.cache import cache

from core.runtime.hub_runtime_profile import resolve_hub_runtime_profile
from server.immoapp_server.business_metrics_match import (
    record_match_runtime_profile_state,
    record_match_runtime_profile_transition,
)
from server.services import runtime_pressure_tripwire
from server.services.postgres_match_health import MatchArtifactHealthSnapshot

logger = logging.getLogger(__name__)

_PROFILE_STATE_CACHE_KEY = "immoapp:match_runtime_profile:state"
_PROFILE_CACHE_TIMEOUT_SECONDS = 7 * 24 * 60 * 60
_GREEN_PROFILE = "green"
_YELLOW_PROFILE = "yellow"
_RED_PROFILE = "red"
_AUTO_PROFILE = "auto"
_REASON_COLD_START = "cold_start_no_baseline"
_REASON_STALE = "stale_health_snapshot_fail_safe"
_REASON_CACHE_UNAVAILABLE = "cache_unavailable"
_REASON_TRIPWIRE = "tripwire_floor"


@dataclass(frozen=True)
class MatchRuntimeProfileSettings:
    name: str
    demande_batch_size: int
    task_chunk_size: int
    full_sql_threshold: int


@dataclass(frozen=True)
class MatchRuntimeProfileState:
    profile: str
    reason: str
    updated_at: str
    sample_age_seconds: int
    stale: bool


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _parse_int_env(name: str, default: int, *, floor: int, ceiling: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = int(default)
    return max(floor, min(value, ceiling))


def _profile_mode() -> str:
    raw = os.environ.get("IMMOAPP_MATCH_RUNTIME_PROFILE", _AUTO_PROFILE).strip().lower()
    return (
        raw
        if raw in {_AUTO_PROFILE, _GREEN_PROFILE, _YELLOW_PROFILE, _RED_PROFILE}
        else _AUTO_PROFILE
    )


def _stale_seconds() -> int:
    return _parse_int_env(
        "IMMOAPP_MATCH_PROFILE_SAMPLE_STALE_SECONDS", 900, floor=60, ceiling=86400
    )


def _yellow_dead_ratio() -> float:
    return float(os.environ.get("IMMOAPP_MATCH_HEALTH_YELLOW_DEAD_RATIO", "0.15") or 0.15)


def _red_dead_ratio() -> float:
    return float(os.environ.get("IMMOAPP_MATCH_HEALTH_RED_DEAD_RATIO", "0.25") or 0.25)


def _yellow_autovac_lag_seconds() -> int:
    return _parse_int_env(
        "IMMOAPP_MATCH_HEALTH_YELLOW_AUTOVAC_LAG_SECONDS", 1200, floor=60, ceiling=86400
    )


def _red_autovac_lag_seconds() -> int:
    return _parse_int_env(
        "IMMOAPP_MATCH_HEALTH_RED_AUTOVAC_LAG_SECONDS", 2400, floor=60, ceiling=86400
    )


def _yellow_temp_bytes_delta() -> int:
    return _parse_int_env(
        "IMMOAPP_MATCH_HEALTH_YELLOW_TEMP_BYTES_DELTA", 134217728, floor=1, ceiling=2**63 - 1
    )


def _red_temp_bytes_delta() -> int:
    return _parse_int_env(
        "IMMOAPP_MATCH_HEALTH_RED_TEMP_BYTES_DELTA", 536870912, floor=1, ceiling=2**63 - 1
    )


def _yellow_conn_ratio() -> float:
    return float(os.environ.get("IMMOAPP_MATCH_HEALTH_YELLOW_CONN_RATIO", "0.80") or 0.80)


def _red_conn_ratio() -> float:
    return float(os.environ.get("IMMOAPP_MATCH_HEALTH_RED_CONN_RATIO", "0.90") or 0.90)


def _yellow_index_bloat_bytes() -> int:
    return _parse_int_env(
        "IMMOAPP_MATCH_HEALTH_YELLOW_INDEX_BLOAT_BYTES", 524288000, floor=1, ceiling=2**63 - 1
    )


def _red_index_bloat_bytes() -> int:
    return _parse_int_env(
        "IMMOAPP_MATCH_HEALTH_RED_INDEX_BLOAT_BYTES", 1073741824, floor=1, ceiling=2**63 - 1
    )


def _green_settings() -> MatchRuntimeProfileSettings:
    return MatchRuntimeProfileSettings(
        name=_GREEN_PROFILE,
        demande_batch_size=_parse_int_env(
            "IMMOAPP_MATCH_PAIRS_DEMANDE_BATCH_SIZE", 250, floor=10, ceiling=2000
        ),
        task_chunk_size=_parse_int_env(
            "IMMOAPP_MATCH_PAIRS_TASK_CHUNK_SIZE", 1000, floor=50, ceiling=5000
        ),
        full_sql_threshold=_parse_int_env(
            "IMMOAPP_MATCH_PAIRS_FULL_SQL_THRESHOLD", 250, floor=50, ceiling=5000
        ),
    )


def _yellow_settings() -> MatchRuntimeProfileSettings:
    green = _green_settings()
    return MatchRuntimeProfileSettings(
        name=_YELLOW_PROFILE,
        demande_batch_size=min(green.demande_batch_size, 200),
        task_chunk_size=min(green.task_chunk_size, 750),
        full_sql_threshold=min(green.full_sql_threshold, 200),
    )


def _red_settings() -> MatchRuntimeProfileSettings:
    green = _green_settings()
    return MatchRuntimeProfileSettings(
        name=_RED_PROFILE,
        demande_batch_size=min(green.demande_batch_size, 125),
        task_chunk_size=min(green.task_chunk_size, 500),
        full_sql_threshold=min(green.full_sql_threshold, 125),
    )


def settings_for_profile(profile: str) -> MatchRuntimeProfileSettings:
    normalized = str(profile or _YELLOW_PROFILE)
    if normalized == _GREEN_PROFILE:
        settings = _green_settings()
    elif normalized == _RED_PROFILE:
        settings = _red_settings()
    else:
        settings = _yellow_settings()
    return _bound_settings_by_hub_profile(settings)


def _bound_settings_by_hub_profile(
    settings: MatchRuntimeProfileSettings,
) -> MatchRuntimeProfileSettings:
    hub_limits = resolve_hub_runtime_profile().effective_limits()
    return MatchRuntimeProfileSettings(
        name=settings.name,
        demande_batch_size=min(settings.demande_batch_size, hub_limits.match_batch_size),
        task_chunk_size=min(settings.task_chunk_size, max(hub_limits.match_batch_size, 50)),
        full_sql_threshold=min(settings.full_sql_threshold, hub_limits.match_batch_size),
    )


def _profile_rank(profile: str) -> int:
    normalized = str(profile or _YELLOW_PROFILE).strip().lower()
    if normalized == _RED_PROFILE:
        return 3
    if normalized == _YELLOW_PROFILE:
        return 2
    return 1


def _apply_tripwire_floor(state: MatchRuntimeProfileState) -> MatchRuntimeProfileState:
    override = runtime_pressure_tripwire.current_override()
    if override is None:
        return state
    override_profile = str(override.profile or _RED_PROFILE).strip().lower() or _RED_PROFILE
    if _profile_rank(override_profile) <= _profile_rank(state.profile):
        return state
    return MatchRuntimeProfileState(
        profile=override_profile,
        reason=f"{_REASON_TRIPWIRE}:{override.reason}",
        updated_at=override.created_at,
        sample_age_seconds=0,
        stale=False,
    )


def _safe_cache_get_dict(key: str) -> dict[str, Any] | None:
    try:
        payload = cache.get(key)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else {}


def _safe_cache_set_dict(key: str, payload: dict[str, Any]) -> None:
    cache.set(key, payload, timeout=_PROFILE_CACHE_TIMEOUT_SECONDS)


def _sample_age_seconds(captured_at: str | None) -> int:
    if not captured_at:
        return _stale_seconds() + 1
    try:
        captured = datetime.fromisoformat(str(captured_at))
    except ValueError:
        return _stale_seconds() + 1
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    return max(0, int((_utc_now() - captured).total_seconds()))


def sample_age_seconds_from_captured_at(captured_at: str | None) -> int:
    return _sample_age_seconds(captured_at)


def _state_from_payload(payload: Mapping[str, Any] | None) -> MatchRuntimeProfileState:
    data = dict(payload or {})
    return MatchRuntimeProfileState(
        profile=str(data.get("profile") or _YELLOW_PROFILE),
        reason=str(data.get("reason") or _REASON_COLD_START),
        updated_at=str(data.get("updated_at") or _utc_now().isoformat()),
        sample_age_seconds=max(0, int(data.get("sample_age_seconds") or 0)),
        stale=bool(data.get("stale", False)),
    )


def load_profile_state() -> MatchRuntimeProfileState | None:
    payload = _safe_cache_get_dict(_PROFILE_STATE_CACHE_KEY)
    if payload is None:
        return MatchRuntimeProfileState(
            profile=_YELLOW_PROFILE,
            reason=_REASON_CACHE_UNAVAILABLE,
            updated_at=_utc_now().isoformat(),
            sample_age_seconds=_stale_seconds() + 1,
            stale=True,
        )
    if not payload:
        return None
    return _state_from_payload(payload)


def raw_profile_state_payload() -> dict[str, Any] | None:
    payload = _safe_cache_get_dict(_PROFILE_STATE_CACHE_KEY)
    if payload is None:
        return None
    return dict(payload)


def _table_dead_ratio(snapshot: MatchArtifactHealthSnapshot, threshold: float) -> bool:
    db_snapshot = snapshot.db_snapshot
    return (
        db_snapshot.match_candidates.dead_ratio >= threshold
        or db_snapshot.match_pairs.dead_ratio >= threshold
    )


def _table_index_bloat(snapshot: MatchArtifactHealthSnapshot, threshold: int) -> bool:
    db_snapshot = snapshot.db_snapshot
    return (
        db_snapshot.match_candidates.index_bloat_estimate_bytes > threshold
        or db_snapshot.match_pairs.index_bloat_estimate_bytes > threshold
    )


def _vacuum_lag_exceeded(
    snapshot: MatchArtifactHealthSnapshot, *, lag_seconds: int, dead_tuples: int
) -> bool:
    for table in (snapshot.db_snapshot.match_candidates, snapshot.db_snapshot.match_pairs):
        if table.dead_tuples < dead_tuples:
            continue
        if table.vacuum_lag_seconds is not None and table.vacuum_lag_seconds >= lag_seconds:
            return True
    return False


def _timeout_delta(snapshot: MatchArtifactHealthSnapshot, *, kind: str) -> int:
    if kind == "statement":
        return int(snapshot.db_snapshot.statement_timeout_delta_5m)
    return int(snapshot.db_snapshot.lock_timeout_delta_5m)


def _red_violation(snapshot: MatchArtifactHealthSnapshot) -> str | None:
    if _table_dead_ratio(snapshot, _red_dead_ratio()):
        return "red_dead_ratio"
    if _table_index_bloat(snapshot, _red_index_bloat_bytes()):
        return "red_index_bloat"
    if _vacuum_lag_exceeded(snapshot, lag_seconds=_red_autovac_lag_seconds(), dead_tuples=100000):
        return "red_autovacuum_lag"
    if snapshot.db_snapshot.temp_bytes_delta_5m >= _red_temp_bytes_delta():
        return "red_temp_bytes"
    if snapshot.db_snapshot.active_connection_ratio >= _red_conn_ratio():
        return "red_connection_ratio"
    if _timeout_delta(snapshot, kind="statement") >= 3:
        return "red_statement_timeout"
    if _timeout_delta(snapshot, kind="lock") >= 3:
        return "red_lock_timeout"
    return None


def _yellow_violation(snapshot: MatchArtifactHealthSnapshot) -> str | None:
    if _table_dead_ratio(snapshot, _yellow_dead_ratio()):
        return "yellow_dead_ratio"
    if _table_index_bloat(snapshot, _yellow_index_bloat_bytes()):
        return "yellow_index_bloat"
    if _vacuum_lag_exceeded(snapshot, lag_seconds=_yellow_autovac_lag_seconds(), dead_tuples=50000):
        return "yellow_autovacuum_lag"
    if snapshot.db_snapshot.temp_bytes_delta_5m >= _yellow_temp_bytes_delta():
        return "yellow_temp_bytes"
    if snapshot.db_snapshot.active_connection_ratio >= _yellow_conn_ratio():
        return "yellow_connection_ratio"
    if _timeout_delta(snapshot, kind="statement") >= 1:
        return "yellow_statement_timeout"
    if _timeout_delta(snapshot, kind="lock") >= 1:
        return "yellow_lock_timeout"
    return None


def evaluate_profile_transition(
    snapshot: MatchArtifactHealthSnapshot,
    current_state: Mapping[str, Any] | MatchRuntimeProfileState | None,
) -> MatchRuntimeProfileState:
    now = _utc_now().isoformat()
    current_payload = dict(
        current_state
        if isinstance(current_state, Mapping)
        else asdict(current_state) if current_state else {}
    )
    if current_state is None:
        return MatchRuntimeProfileState(
            profile=_YELLOW_PROFILE,
            reason=_REASON_COLD_START,
            updated_at=now,
            sample_age_seconds=0,
            stale=False,
        )

    profile = str(current_payload.get("profile") or _YELLOW_PROFILE)
    red_violation = _red_violation(snapshot)
    yellow_violation = _yellow_violation(snapshot)
    healthy_red_streak = (
        (int(current_payload.get("healthy_red_streak") or 0) + 1) if not red_violation else 0
    )
    healthy_green_streak = (
        (int(current_payload.get("healthy_green_streak") or 0) + 1)
        if not red_violation and not yellow_violation
        else 0
    )

    next_profile = profile
    reason = str(current_payload.get("reason") or _REASON_COLD_START)

    if red_violation:
        next_profile = _RED_PROFILE
        reason = red_violation
    elif profile == _RED_PROFILE:
        if healthy_red_streak >= 3:
            next_profile = _YELLOW_PROFILE
            reason = "yellow_recovered_from_red"
        else:
            reason = "red_stable"
    elif yellow_violation:
        next_profile = _YELLOW_PROFILE
        reason = yellow_violation
    elif profile == _YELLOW_PROFILE:
        if healthy_green_streak >= 3:
            next_profile = _GREEN_PROFILE
            reason = "green_recovered"
        else:
            reason = "yellow_stable"
    elif reason == _REASON_COLD_START and healthy_green_streak < 3:
        next_profile = _YELLOW_PROFILE
        reason = _REASON_COLD_START
    else:
        next_profile = _GREEN_PROFILE
        reason = "green_stable"

    return MatchRuntimeProfileState(
        profile=next_profile,
        reason=reason,
        updated_at=now,
        sample_age_seconds=0,
        stale=False,
    )


def store_profile_state(
    state: MatchRuntimeProfileState,
    *,
    snapshot_captured_at: str | None,
    current_payload: Mapping[str, Any] | None,
    snapshot: MatchArtifactHealthSnapshot,
) -> MatchRuntimeProfileState:
    prior_payload = dict(current_payload or {})
    red_violation = _red_violation(snapshot)
    yellow_violation = _yellow_violation(snapshot)
    payload = {
        "profile": state.profile,
        "reason": state.reason,
        "updated_at": state.updated_at,
        "sample_age_seconds": 0,
        "stale": False,
        "snapshot_captured_at": snapshot_captured_at or state.updated_at,
        "red_violation_streak": (
            (int(prior_payload.get("red_violation_streak") or 0) + 1) if red_violation else 0
        ),
        "yellow_violation_streak": (
            (int(prior_payload.get("yellow_violation_streak") or 0) + 1) if yellow_violation else 0
        ),
        "healthy_red_streak": (
            (int(prior_payload.get("healthy_red_streak") or 0) + 1) if not red_violation else 0
        ),
        "healthy_green_streak": (
            (int(prior_payload.get("healthy_green_streak") or 0) + 1)
            if not red_violation and not yellow_violation
            else 0
        ),
    }
    _safe_cache_set_dict(_PROFILE_STATE_CACHE_KEY, payload)
    previous_profile = str(prior_payload.get("profile") or "")
    if previous_profile and previous_profile != state.profile:
        record_match_runtime_profile_transition(profile=state.profile, reason=state.reason)
    record_match_runtime_profile_state(
        profile=state.profile,
        reason=state.reason,
        sample_age_seconds=0,
        stale=False,
    )
    return _state_from_payload(payload)


def resolve_effective_profile() -> MatchRuntimeProfileSettings:
    mode = _profile_mode()
    if mode in {_GREEN_PROFILE, _YELLOW_PROFILE, _RED_PROFILE}:
        record_match_runtime_profile_state(
            profile=mode,
            reason=f"manual_{mode}",
            sample_age_seconds=0,
            stale=False,
        )
        return settings_for_profile(
            _apply_tripwire_floor(
                MatchRuntimeProfileState(
                    profile=mode,
                    reason=f"manual_{mode}",
                    updated_at=_utc_now().isoformat(),
                    sample_age_seconds=0,
                    stale=False,
                )
            ).profile
        )

    payload = _safe_cache_get_dict(_PROFILE_STATE_CACHE_KEY)
    if payload is None:
        record_match_runtime_profile_state(
            profile=_YELLOW_PROFILE,
            reason=_REASON_CACHE_UNAVAILABLE,
            sample_age_seconds=_stale_seconds() + 1,
            stale=True,
        )
        return settings_for_profile(
            _apply_tripwire_floor(
                MatchRuntimeProfileState(
                    profile=_YELLOW_PROFILE,
                    reason=_REASON_CACHE_UNAVAILABLE,
                    updated_at=_utc_now().isoformat(),
                    sample_age_seconds=_stale_seconds() + 1,
                    stale=True,
                )
            ).profile
        )
    if not payload:
        record_match_runtime_profile_state(
            profile=_YELLOW_PROFILE,
            reason=_REASON_COLD_START,
            sample_age_seconds=_stale_seconds() + 1,
            stale=True,
        )
        return settings_for_profile(
            _apply_tripwire_floor(
                MatchRuntimeProfileState(
                    profile=_YELLOW_PROFILE,
                    reason=_REASON_COLD_START,
                    updated_at=_utc_now().isoformat(),
                    sample_age_seconds=_stale_seconds() + 1,
                    stale=True,
                )
            ).profile
        )

    sample_age_seconds = _sample_age_seconds(str(payload.get("snapshot_captured_at") or ""))
    if sample_age_seconds > _stale_seconds():
        record_match_runtime_profile_state(
            profile=_YELLOW_PROFILE,
            reason=_REASON_STALE,
            sample_age_seconds=sample_age_seconds,
            stale=True,
        )
        return settings_for_profile(
            _apply_tripwire_floor(
                MatchRuntimeProfileState(
                    profile=_YELLOW_PROFILE,
                    reason=_REASON_STALE,
                    updated_at=str(payload.get("updated_at") or _utc_now().isoformat()),
                    sample_age_seconds=sample_age_seconds,
                    stale=True,
                )
            ).profile
        )

    state = _apply_tripwire_floor(
        _state_from_payload({**payload, "sample_age_seconds": sample_age_seconds, "stale": False})
    )
    record_match_runtime_profile_state(
        profile=state.profile,
        reason=state.reason,
        sample_age_seconds=sample_age_seconds,
        stale=False,
    )
    return settings_for_profile(state.profile)


def effective_profile_state() -> MatchRuntimeProfileState:
    mode = _profile_mode()
    if mode in {_GREEN_PROFILE, _YELLOW_PROFILE, _RED_PROFILE}:
        return _apply_tripwire_floor(
            MatchRuntimeProfileState(
                profile=mode,
                reason=f"manual_{mode}",
                updated_at=_utc_now().isoformat(),
                sample_age_seconds=0,
                stale=False,
            )
        )
    payload = _safe_cache_get_dict(_PROFILE_STATE_CACHE_KEY)
    if payload is None:
        return _apply_tripwire_floor(
            MatchRuntimeProfileState(
                profile=_YELLOW_PROFILE,
                reason=_REASON_CACHE_UNAVAILABLE,
                updated_at=_utc_now().isoformat(),
                sample_age_seconds=_stale_seconds() + 1,
                stale=True,
            )
        )
    if not payload:
        return _apply_tripwire_floor(
            MatchRuntimeProfileState(
                profile=_YELLOW_PROFILE,
                reason=_REASON_COLD_START,
                updated_at=_utc_now().isoformat(),
                sample_age_seconds=_stale_seconds() + 1,
                stale=True,
            )
        )
    sample_age_seconds = _sample_age_seconds(str(payload.get("snapshot_captured_at") or ""))
    if sample_age_seconds > _stale_seconds():
        return _apply_tripwire_floor(
            MatchRuntimeProfileState(
                profile=_YELLOW_PROFILE,
                reason=_REASON_STALE,
                updated_at=str(payload.get("updated_at") or _utc_now().isoformat()),
                sample_age_seconds=sample_age_seconds,
                stale=True,
            )
        )
    return _apply_tripwire_floor(
        _state_from_payload({**payload, "sample_age_seconds": sample_age_seconds, "stale": False})
    )


__all__ = [
    "MatchRuntimeProfileSettings",
    "MatchRuntimeProfileState",
    "effective_profile_state",
    "evaluate_profile_transition",
    "load_profile_state",
    "raw_profile_state_payload",
    "resolve_effective_profile",
    "sample_age_seconds_from_captured_at",
    "settings_for_profile",
    "store_profile_state",
]
