"""Match and cache business metrics owner."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, cast

from server.immoapp_server.business_metrics_core import (
    _counter,
    _histogram,
    _histogram_ms,
    _NoopCounter,
    _NoopHistogram,
    _observable_gauge,
)

logger = logging.getLogger(__name__)

_MATCH_RUNTIME_PROFILE_SNAPSHOT_LOCK = threading.Lock()
_MATCH_RUNTIME_PROFILE_SNAPSHOT: dict[str, object] = {
    "profile_value": 1.0,
    "stale": 0.0,
}


def _coerce_float(value: object) -> float:
    try:
        return float(cast(Any, value))
    except Exception:
        return 0.0


def _coerce_int(value: object) -> int:
    try:
        return int(cast(Any, value))
    except Exception:
        return 0


@lru_cache(maxsize=1)
def _match_pair_runs_counter() -> _NoopCounter:
    return _counter(
        "immoapp.matcher.pair_rebuild.runs",
        "Pair rebuild runs by outcome.",
    )


@lru_cache(maxsize=1)
def _match_pair_rows_counter() -> _NoopCounter:
    return _counter(
        "immoapp.matcher.pair_rebuild.rows",
        "Pair rebuild candidate/stored row counts.",
    )


@lru_cache(maxsize=1)
def _match_pair_duration_hist() -> _NoopHistogram:
    return _histogram_ms(
        "immoapp.matcher.pair_rebuild.duration.ms",
        "Matcher pair rebuild duration.",
    )


@lru_cache(maxsize=1)
def _match_artifact_pipeline_counter() -> _NoopCounter:
    return _counter(
        "immoapp.matcher.artifact_pipeline.runs",
        "Artifact pipeline runs by mode and outcome.",
    )


@lru_cache(maxsize=1)
def _match_artifact_pipeline_rows_counter() -> _NoopCounter:
    return _counter(
        "immoapp.matcher.artifact_pipeline.rows",
        "Artifact pipeline candidate, ranked, and stored row counts.",
    )


@lru_cache(maxsize=1)
def _match_artifact_pipeline_duration_hist() -> _NoopHistogram:
    return _histogram_ms(
        "immoapp.matcher.artifact_pipeline.duration.ms",
        "Artifact pipeline duration by mode and outcome.",
    )


@lru_cache(maxsize=1)
def _match_cache_lookup_counter() -> _NoopCounter:
    return _counter(
        "immoapp.matcher.cache.lookups",
        "Match cache lookups by hit/miss outcome.",
    )


@lru_cache(maxsize=1)
def _cache_event_counter() -> _NoopCounter:
    return _counter(
        "immoapp.cache.events",
        "Cache hits, misses, fills, evictions, and rejects by cache and layer.",
    )


@lru_cache(maxsize=1)
def _cache_fill_latency_hist() -> _NoopHistogram:
    return _histogram_ms(
        "immoapp.cache.fill.duration.ms",
        "Cache fill latency by cache and layer.",
    )


@lru_cache(maxsize=1)
def _cache_payload_bytes_hist() -> _NoopHistogram:
    return _histogram(
        "immoapp.cache.payload.bytes",
        "By",
        "Cache payload sizes by cache and layer.",
    )


@lru_cache(maxsize=1)
def _cache_pressure_hist() -> _NoopHistogram:
    return _histogram(
        "immoapp.cache.pressure",
        "1",
        "Cache entries and bytes tracked under pressure.",
    )


def _match_runtime_profile_observations(kind: str) -> list[tuple[float, dict[str, object]]]:
    with _MATCH_RUNTIME_PROFILE_SNAPSHOT_LOCK:
        snapshot = dict(_MATCH_RUNTIME_PROFILE_SNAPSHOT)
    raw_value = snapshot.get(kind, 0.0)
    value = _coerce_float(raw_value)
    return [(value, {"kind": kind})]


@lru_cache(maxsize=1)
def _match_artifact_timeout_counter() -> _NoopCounter:
    return _counter(
        "immoapp.matcher.artifact_timeout.events",
        "Statement and lock timeout events for the match artifact pipeline.",
    )


@lru_cache(maxsize=1)
def _match_runtime_profile_transition_counter() -> _NoopCounter:
    return _counter(
        "immoapp.matcher.runtime_profile.transitions",
        "Match runtime profile transitions by destination profile and reason.",
    )


@lru_cache(maxsize=1)
def _match_runtime_profile_gauge() -> object | None:
    return _observable_gauge(
        "immoapp.matcher.runtime_profile.state",
        "Current match runtime profile state.",
        lambda: _match_runtime_profile_observations("profile_value"),
    )


@lru_cache(maxsize=1)
def _match_runtime_profile_stale_gauge() -> object | None:
    return _observable_gauge(
        "immoapp.matcher.runtime_profile.stale",
        "Whether the current match runtime profile state is stale.",
        lambda: _match_runtime_profile_observations("stale"),
    )


def record_match_pair_rebuild(
    *,
    outcome: str,
    candidates: int,
    stored: int,
    duration_s: float,
) -> None:
    attrs = {"outcome": outcome}
    _match_pair_runs_counter().add(1, attributes=attrs)
    if candidates > 0:
        _match_pair_rows_counter().add(candidates, attributes={**attrs, "kind": "candidates"})
    if stored > 0:
        _match_pair_rows_counter().add(stored, attributes={**attrs, "kind": "stored"})
    _match_pair_duration_hist().record(duration_s * 1000.0, attributes=attrs)


def record_match_artifact_pipeline(
    *,
    mode: str,
    outcome: str,
    batch_size: int,
    candidates: int,
    ranked: int,
    stored: int,
    duration_s: float,
) -> None:
    attrs = {"mode": str(mode or "unknown"), "outcome": str(outcome or "unknown")}
    _match_artifact_pipeline_counter().add(
        1,
        attributes={**attrs, "kind": "run"},
    )
    if batch_size > 0:
        _match_artifact_pipeline_rows_counter().add(
            int(batch_size),
            attributes={**attrs, "kind": "batch_size"},
        )
    if candidates > 0:
        _match_artifact_pipeline_rows_counter().add(
            int(candidates),
            attributes={**attrs, "kind": "candidates"},
        )
    if ranked > 0:
        _match_artifact_pipeline_rows_counter().add(
            int(ranked),
            attributes={**attrs, "kind": "ranked"},
        )
    if stored > 0:
        _match_artifact_pipeline_rows_counter().add(
            int(stored),
            attributes={**attrs, "kind": "stored"},
        )
    _match_artifact_pipeline_duration_hist().record(
        max(0.0, float(duration_s)) * 1000.0,
        attributes=attrs,
    )


def record_match_cache_lookup(*, cache_name: str, outcome: str, count: int = 1) -> None:
    if count <= 0:
        return
    _match_cache_lookup_counter().add(
        count,
        attributes={"cache_name": cache_name, "outcome": outcome},
    )


def record_cache_event(
    cache_name: str,
    layer: str,
    outcome: str,
    tenant_scope: str,
    count: int = 1,
) -> None:
    _ = tenant_scope
    if count <= 0:
        return
    _cache_event_counter().add(
        int(count),
        attributes={
            "cache_name": str(cache_name or "unknown"),
            "outcome": str(outcome or "unknown"),
            "phase": str(layer or "unknown"),
        },
    )


def record_cache_fill_latency(cache_name: str, layer: str, duration_s: float) -> None:
    _cache_fill_latency_hist().record(
        max(0.0, float(duration_s)) * 1000.0,
        attributes={"cache_name": str(cache_name or "unknown"), "phase": str(layer or "unknown")},
    )


def record_cache_payload_bytes(cache_name: str, layer: str, bytes_size: int) -> None:
    _cache_payload_bytes_hist().record(
        max(0.0, float(bytes_size)),
        attributes={"cache_name": str(cache_name or "unknown"), "phase": str(layer or "unknown")},
    )


def record_cache_pressure(
    cache_name: str,
    layer: str,
    outcome: str,
    bytes_total: int,
    entries_total: int,
) -> None:
    attrs = {
        "cache_name": str(cache_name or "unknown"),
        "phase": str(layer or "unknown"),
        "outcome": str(outcome or "unknown"),
    }
    _cache_pressure_hist().record(
        max(0.0, float(bytes_total)), attributes={**attrs, "kind": "bytes"}
    )
    _cache_pressure_hist().record(
        max(0.0, float(entries_total)),
        attributes={**attrs, "kind": "entries"},
    )


def record_match_artifact_timeout(*, kind: str, count: int = 1) -> None:
    normalized_kind = str(kind or "unknown")
    if count <= 0:
        return
    _match_artifact_timeout_counter().add(int(count), attributes={"kind": normalized_kind})
    column = {
        "statement_timeout": "statement_timeout_count",
        "lock_timeout": "lock_timeout_count",
    }.get(normalized_kind)
    if not column:
        return
    try:
        from server.pg.uow import get_uow, use_schema, use_security_context

        with use_schema("public"), use_security_context(agency_id=None, is_superuser=True):
            with get_uow().transaction(is_superuser=True) as session:
                session.execute("""
                    INSERT INTO match_artifact_timeout_counters (
                        id,
                        statement_timeout_count,
                        lock_timeout_count,
                        updated_at
                    )
                    VALUES (1, 0, 0, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO NOTHING
                    """)
                session.execute(
                    f"""
                    UPDATE match_artifact_timeout_counters
                    SET {column} = {column} + %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                    """,
                    (int(count),),
                )
    except Exception:
        logger.warning(
            "Failed to persist match artifact timeout counter to the canonical DB owner",
            exc_info=True,
        )


def read_match_artifact_timeout_counters() -> dict[str, int]:
    try:
        from server.pg.uow import get_uow, use_schema, use_security_context

        with use_schema("public"), use_security_context(agency_id=None, is_superuser=True):
            with get_uow().session(is_superuser=True) as session:
                row = session.execute("""
                    SELECT
                        statement_timeout_count,
                        lock_timeout_count
                    FROM match_artifact_timeout_counters
                    WHERE id = 1
                    """).fetchone()
    except Exception:
        logger.warning(
            "Failed to read canonical match artifact timeout counters; returning zeros",
            exc_info=True,
        )
        row = None
    row_mapping: Mapping[str, object]
    if isinstance(row, Mapping):
        row_mapping = row
    elif row is not None and hasattr(row, "_mapping"):
        maybe_mapping = cast(Any, row)._mapping
        row_mapping = maybe_mapping if isinstance(maybe_mapping, Mapping) else {}
    else:
        row_mapping = {}
    return {
        "statement_timeout_count": max(0, _coerce_int(row_mapping.get("statement_timeout_count"))),
        "lock_timeout_count": max(0, _coerce_int(row_mapping.get("lock_timeout_count"))),
    }


def record_match_runtime_profile_transition(*, profile: str, reason: str) -> None:
    _match_runtime_profile_transition_counter().add(
        1,
        attributes={
            "profile": str(profile or "unknown"),
            "reason": str(reason or "unknown"),
        },
    )


def record_match_runtime_profile_state(
    *,
    profile: str,
    reason: str,
    sample_age_seconds: int,
    stale: bool,
) -> None:
    _match_runtime_profile_gauge()
    _match_runtime_profile_stale_gauge()
    profile_value = {"green": 3.0, "yellow": 2.0, "red": 1.0}.get(str(profile or ""), 0.0)
    with _MATCH_RUNTIME_PROFILE_SNAPSHOT_LOCK:
        _MATCH_RUNTIME_PROFILE_SNAPSHOT.update(
            {
                "profile_value": profile_value,
                "stale": 1.0 if stale else 0.0,
                "sample_age_seconds": max(0.0, float(sample_age_seconds)),
                "reason_hash": float(abs(hash(str(reason or "unknown"))) % 10000),
            }
        )


__all__ = [
    "read_match_artifact_timeout_counters",
    "record_cache_event",
    "record_cache_fill_latency",
    "record_cache_payload_bytes",
    "record_cache_pressure",
    "record_match_artifact_pipeline",
    "record_match_artifact_timeout",
    "record_match_cache_lookup",
    "record_match_pair_rebuild",
    "record_match_runtime_profile_state",
    "record_match_runtime_profile_transition",
]
