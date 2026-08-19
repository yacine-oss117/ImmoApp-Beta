"""Postgres health sampling for hot match artifact tables."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import connection, transaction

from server.pg.uow import get_uow, use_schema, use_security_context

logger = logging.getLogger(__name__)

_MATCH_TABLES = ("match_candidates", "match_pairs")
_INDEX_ENTRY_SIZE_BYTES = 64


@dataclass(frozen=True)
class MatchArtifactTableHealth:
    table_name: str
    live_tuples: int
    dead_tuples: int
    dead_ratio: float
    table_bytes: int
    index_bytes: int
    total_bytes: int
    index_bloat_estimate_bytes: int
    last_autovacuum: str | None
    autovacuum_count: int
    last_autoanalyze: str | None
    autoanalyze_count: int
    vacuum_lag_seconds: int | None
    analyze_lag_seconds: int | None


@dataclass(frozen=True)
class MatchArtifactDbSnapshot:
    captured_at: str
    active_connections: int
    max_connections: int
    active_connection_ratio: float
    temp_bytes_total: int
    temp_bytes_delta_5m: int
    temp_files_total: int
    temp_files_delta_5m: int
    statement_timeout_count: int
    lock_timeout_count: int
    statement_timeout_delta_5m: int
    lock_timeout_delta_5m: int
    match_candidates: MatchArtifactTableHealth
    match_pairs: MatchArtifactTableHealth


@dataclass(frozen=True)
class MatchArtifactHealthSnapshot:
    db_snapshot: MatchArtifactDbSnapshot
    collector_ok: bool
    collector_error: str | None


@dataclass(frozen=True)
class _HealthSampleBaseline:
    temp_bytes_total: int | None
    temp_files_total: int | None
    statement_timeout_count: int | None
    lock_timeout_count: int | None


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _lag_seconds(value: object, *, now: datetime) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        candidate = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return max(0, int((now - candidate).total_seconds()))
    return None


def _clamp_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, float(numerator) / float(denominator)))


def _compute_delta(current: int, previous: int | None) -> int:
    if previous is None:
        return 0
    if int(current) < int(previous):
        return 0
    return max(0, int(current) - int(previous))


def _row_dict(cursor: Any, row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {desc[0]: value for desc, value in zip(cursor.description, row, strict=False)}


def _load_table_rows(cursor: Any) -> dict[str, dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            st.relname AS table_name,
            COALESCE(st.n_live_tup, 0)::bigint AS live_tuples,
            COALESCE(st.n_dead_tup, 0)::bigint AS dead_tuples,
            pg_relation_size(st.relid)::bigint AS table_bytes,
            pg_indexes_size(st.relid)::bigint AS index_bytes,
            pg_total_relation_size(st.relid)::bigint AS total_bytes,
            st.last_autovacuum,
            COALESCE(st.autovacuum_count, 0)::bigint AS autovacuum_count,
            st.last_autoanalyze,
            COALESCE(st.autoanalyze_count, 0)::bigint AS autoanalyze_count
        FROM pg_stat_user_tables st
        WHERE st.relname = ANY(%s)
        """,
        (list(_MATCH_TABLES),),
    )
    rows = cursor.fetchall()
    return {str(item.get("table_name")): item for item in (_row_dict(cursor, row) for row in rows)}


def _load_connection_snapshot(cursor: Any) -> tuple[int, int]:
    cursor.execute("""
        SELECT
            (SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active' AND pid <> pg_backend_pid()) AS active_connections,
            current_setting('max_connections')::int AS max_connections
        """)
    row = _row_dict(cursor, cursor.fetchone())
    return max(0, int(row.get("active_connections") or 0)), max(
        1, int(row.get("max_connections") or 1)
    )


def _load_temp_counters(cursor: Any) -> tuple[int, int]:
    cursor.execute("""
        SELECT COALESCE(temp_bytes, 0)::bigint AS temp_bytes_total,
               COALESCE(temp_files, 0)::bigint AS temp_files_total
        FROM pg_stat_database
        WHERE datname = current_database()
        """)
    row = _row_dict(cursor, cursor.fetchone())
    return max(0, int(row.get("temp_bytes_total") or 0)), max(
        0, int(row.get("temp_files_total") or 0)
    )


def _load_timeout_counters(cursor: Any) -> tuple[int, int]:
    cursor.execute("""
        SELECT
            statement_timeout_count,
            lock_timeout_count
        FROM match_artifact_timeout_counters
        WHERE id = 1
        """)
    row = _row_dict(cursor, cursor.fetchone())
    return max(0, int(row.get("statement_timeout_count") or 0)), max(
        0, int(row.get("lock_timeout_count") or 0)
    )


def _load_sample_baseline(
    cursor: Any,
    *,
    captured_before: datetime,
) -> _HealthSampleBaseline:
    cursor.execute(
        """
        SELECT
            temp_bytes_total,
            temp_files_total,
            statement_timeout_count,
            lock_timeout_count
        FROM match_artifact_health_samples
        WHERE captured_at <= %s
        ORDER BY captured_at DESC
        LIMIT 1
        """,
        (captured_before,),
    )
    row = _row_dict(cursor, cursor.fetchone())
    if not row:
        return _HealthSampleBaseline(
            temp_bytes_total=None,
            temp_files_total=None,
            statement_timeout_count=None,
            lock_timeout_count=None,
        )
    return _HealthSampleBaseline(
        temp_bytes_total=max(0, int(row.get("temp_bytes_total") or 0)),
        temp_files_total=max(0, int(row.get("temp_files_total") or 0)),
        statement_timeout_count=max(0, int(row.get("statement_timeout_count") or 0)),
        lock_timeout_count=max(0, int(row.get("lock_timeout_count") or 0)),
    )


def _table_health_from_row(
    table_name: str,
    row: dict[str, Any] | None,
    *,
    now: datetime,
) -> MatchArtifactTableHealth:
    payload = row or {}
    live_tuples = max(0, int(payload.get("live_tuples") or 0))
    dead_tuples = max(0, int(payload.get("dead_tuples") or 0))
    index_bytes = max(0, int(payload.get("index_bytes") or 0))
    index_bloat_estimate_bytes = max(0, index_bytes - (live_tuples * _INDEX_ENTRY_SIZE_BYTES))
    return MatchArtifactTableHealth(
        table_name=table_name,
        live_tuples=live_tuples,
        dead_tuples=dead_tuples,
        dead_ratio=_clamp_ratio(dead_tuples, live_tuples + dead_tuples),
        table_bytes=max(0, int(payload.get("table_bytes") or 0)),
        index_bytes=index_bytes,
        total_bytes=max(0, int(payload.get("total_bytes") or 0)),
        index_bloat_estimate_bytes=index_bloat_estimate_bytes,
        last_autovacuum=_iso_or_none(payload.get("last_autovacuum")),
        autovacuum_count=max(0, int(payload.get("autovacuum_count") or 0)),
        last_autoanalyze=_iso_or_none(payload.get("last_autoanalyze")),
        autoanalyze_count=max(0, int(payload.get("autoanalyze_count") or 0)),
        vacuum_lag_seconds=_lag_seconds(payload.get("last_autovacuum"), now=now),
        analyze_lag_seconds=_lag_seconds(payload.get("last_autoanalyze"), now=now),
    )


def _empty_table_health(table_name: str) -> MatchArtifactTableHealth:
    return MatchArtifactTableHealth(
        table_name=table_name,
        live_tuples=0,
        dead_tuples=0,
        dead_ratio=0.0,
        table_bytes=0,
        index_bytes=0,
        total_bytes=0,
        index_bloat_estimate_bytes=0,
        last_autovacuum=None,
        autovacuum_count=0,
        last_autoanalyze=None,
        autoanalyze_count=0,
        vacuum_lag_seconds=None,
        analyze_lag_seconds=None,
    )


def _empty_db_snapshot() -> MatchArtifactDbSnapshot:
    captured_at = _utc_now().isoformat()
    return MatchArtifactDbSnapshot(
        captured_at=captured_at,
        active_connections=0,
        max_connections=1,
        active_connection_ratio=0.0,
        temp_bytes_total=0,
        temp_bytes_delta_5m=0,
        temp_files_total=0,
        temp_files_delta_5m=0,
        statement_timeout_count=0,
        lock_timeout_count=0,
        statement_timeout_delta_5m=0,
        lock_timeout_delta_5m=0,
        match_candidates=_empty_table_health("match_candidates"),
        match_pairs=_empty_table_health("match_pairs"),
    )


def _empty_snapshot(*, error: str | None = None) -> MatchArtifactHealthSnapshot:
    return MatchArtifactHealthSnapshot(
        db_snapshot=_empty_db_snapshot(),
        collector_ok=False,
        collector_error=error,
    )


def _table_payload(table: MatchArtifactTableHealth) -> dict[str, object]:
    return {
        "table_name": table.table_name,
        "live_tuples": table.live_tuples,
        "dead_tuples": table.dead_tuples,
        "dead_ratio": table.dead_ratio,
        "table_bytes": table.table_bytes,
        "index_bytes": table.index_bytes,
        "total_bytes": table.total_bytes,
        "index_bloat_estimate_bytes": table.index_bloat_estimate_bytes,
        "last_autovacuum": table.last_autovacuum,
        "autovacuum_count": table.autovacuum_count,
        "last_autoanalyze": table.last_autoanalyze,
        "autoanalyze_count": table.autoanalyze_count,
        "vacuum_lag_seconds": table.vacuum_lag_seconds,
        "analyze_lag_seconds": table.analyze_lag_seconds,
    }


def _deserialize_table(
    payload: dict[str, Any] | str | None,
    *,
    table_name: str,
) -> MatchArtifactTableHealth:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = None
    if not isinstance(payload, dict):
        return _empty_table_health(table_name)
    return MatchArtifactTableHealth(
        table_name=str(payload.get("table_name") or table_name),
        live_tuples=max(0, int(payload.get("live_tuples") or 0)),
        dead_tuples=max(0, int(payload.get("dead_tuples") or 0)),
        dead_ratio=max(0.0, float(payload.get("dead_ratio") or 0.0)),
        table_bytes=max(0, int(payload.get("table_bytes") or 0)),
        index_bytes=max(0, int(payload.get("index_bytes") or 0)),
        total_bytes=max(0, int(payload.get("total_bytes") or 0)),
        index_bloat_estimate_bytes=max(0, int(payload.get("index_bloat_estimate_bytes") or 0)),
        last_autovacuum=(
            str(payload.get("last_autovacuum")) if payload.get("last_autovacuum") else None
        ),
        autovacuum_count=max(0, int(payload.get("autovacuum_count") or 0)),
        last_autoanalyze=(
            str(payload.get("last_autoanalyze")) if payload.get("last_autoanalyze") else None
        ),
        autoanalyze_count=max(0, int(payload.get("autoanalyze_count") or 0)),
        vacuum_lag_seconds=(
            max(0, int(payload.get("vacuum_lag_seconds") or 0))
            if payload.get("vacuum_lag_seconds") is not None
            else None
        ),
        analyze_lag_seconds=(
            max(0, int(payload.get("analyze_lag_seconds") or 0))
            if payload.get("analyze_lag_seconds") is not None
            else None
        ),
    )


def _persist_health_snapshot(snapshot: MatchArtifactHealthSnapshot) -> None:
    db_snapshot = snapshot.db_snapshot
    captured_at_dt = datetime.fromisoformat(db_snapshot.captured_at)
    if captured_at_dt.tzinfo is None:
        captured_at_dt = captured_at_dt.replace(tzinfo=UTC)
    captured_minute = captured_at_dt.replace(second=0, microsecond=0)
    with use_schema("public"), use_security_context(agency_id=None, is_superuser=True):
        with get_uow().transaction(is_superuser=True) as session:
            session.execute(
                """
                INSERT INTO match_artifact_health_samples (
                    captured_minute,
                    captured_at,
                    active_connections,
                    max_connections,
                    active_connection_ratio,
                    temp_bytes_total,
                    temp_bytes_delta_5m,
                    temp_files_total,
                    temp_files_delta_5m,
                    statement_timeout_count,
                    lock_timeout_count,
                    statement_timeout_delta_5m,
                    lock_timeout_delta_5m,
                    match_candidates_payload,
                    match_pairs_payload,
                    updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (captured_minute)
                DO UPDATE SET
                    captured_at = EXCLUDED.captured_at,
                    active_connections = EXCLUDED.active_connections,
                    max_connections = EXCLUDED.max_connections,
                    active_connection_ratio = EXCLUDED.active_connection_ratio,
                    temp_bytes_total = EXCLUDED.temp_bytes_total,
                    temp_bytes_delta_5m = EXCLUDED.temp_bytes_delta_5m,
                    temp_files_total = EXCLUDED.temp_files_total,
                    temp_files_delta_5m = EXCLUDED.temp_files_delta_5m,
                    statement_timeout_count = EXCLUDED.statement_timeout_count,
                    lock_timeout_count = EXCLUDED.lock_timeout_count,
                    statement_timeout_delta_5m = EXCLUDED.statement_timeout_delta_5m,
                    lock_timeout_delta_5m = EXCLUDED.lock_timeout_delta_5m,
                    match_candidates_payload = EXCLUDED.match_candidates_payload,
                    match_pairs_payload = EXCLUDED.match_pairs_payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    captured_minute,
                    captured_at_dt,
                    int(db_snapshot.active_connections),
                    int(db_snapshot.max_connections),
                    float(db_snapshot.active_connection_ratio),
                    int(db_snapshot.temp_bytes_total),
                    int(db_snapshot.temp_bytes_delta_5m),
                    int(db_snapshot.temp_files_total),
                    int(db_snapshot.temp_files_delta_5m),
                    int(db_snapshot.statement_timeout_count),
                    int(db_snapshot.lock_timeout_count),
                    int(db_snapshot.statement_timeout_delta_5m),
                    int(db_snapshot.lock_timeout_delta_5m),
                    json.dumps(_table_payload(db_snapshot.match_candidates), sort_keys=True),
                    json.dumps(_table_payload(db_snapshot.match_pairs), sort_keys=True),
                ),
            )


def _snapshot_from_sample_row(row: dict[str, Any]) -> MatchArtifactHealthSnapshot:
    captured_at = _iso_or_none(row.get("captured_at")) or _utc_now().isoformat()
    return MatchArtifactHealthSnapshot(
        db_snapshot=MatchArtifactDbSnapshot(
            captured_at=captured_at,
            active_connections=max(0, int(row.get("active_connections") or 0)),
            max_connections=max(1, int(row.get("max_connections") or 1)),
            active_connection_ratio=max(0.0, float(row.get("active_connection_ratio") or 0.0)),
            temp_bytes_total=max(0, int(row.get("temp_bytes_total") or 0)),
            temp_bytes_delta_5m=max(0, int(row.get("temp_bytes_delta_5m") or 0)),
            temp_files_total=max(0, int(row.get("temp_files_total") or 0)),
            temp_files_delta_5m=max(0, int(row.get("temp_files_delta_5m") or 0)),
            statement_timeout_count=max(0, int(row.get("statement_timeout_count") or 0)),
            lock_timeout_count=max(0, int(row.get("lock_timeout_count") or 0)),
            statement_timeout_delta_5m=max(0, int(row.get("statement_timeout_delta_5m") or 0)),
            lock_timeout_delta_5m=max(0, int(row.get("lock_timeout_delta_5m") or 0)),
            match_candidates=_deserialize_table(
                row.get("match_candidates_payload"),
                table_name="match_candidates",
            ),
            match_pairs=_deserialize_table(
                row.get("match_pairs_payload"),
                table_name="match_pairs",
            ),
        ),
        collector_ok=True,
        collector_error=None,
    )


def collect_match_artifact_db_snapshot() -> MatchArtifactDbSnapshot:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT CURRENT_TIMESTAMP AS captured_at")
            captured_row = _row_dict(cursor, cursor.fetchone())
            captured_at_raw = captured_row.get("captured_at")
            captured_at_dt = (
                captured_at_raw
                if isinstance(captured_at_raw, datetime)
                else datetime.fromisoformat(_iso_or_none(captured_at_raw) or _utc_now().isoformat())
            )
            if captured_at_dt.tzinfo is None:
                captured_at_dt = captured_at_dt.replace(tzinfo=UTC)
            active_connections, max_connections = _load_connection_snapshot(cursor)
            temp_bytes_total, temp_files_total = _load_temp_counters(cursor)
            statement_timeout_count, lock_timeout_count = _load_timeout_counters(cursor)
            baseline = _load_sample_baseline(
                cursor,
                captured_before=captured_at_dt - timedelta(minutes=5),
            )
            table_rows = _load_table_rows(cursor)
    captured_at = _iso_or_none(captured_at_raw) or captured_at_dt.isoformat()
    return MatchArtifactDbSnapshot(
        captured_at=captured_at,
        active_connections=active_connections,
        max_connections=max_connections,
        active_connection_ratio=_clamp_ratio(active_connections, max_connections),
        temp_bytes_total=temp_bytes_total,
        temp_bytes_delta_5m=_compute_delta(temp_bytes_total, baseline.temp_bytes_total),
        temp_files_total=temp_files_total,
        temp_files_delta_5m=_compute_delta(temp_files_total, baseline.temp_files_total),
        statement_timeout_count=statement_timeout_count,
        lock_timeout_count=lock_timeout_count,
        statement_timeout_delta_5m=_compute_delta(
            statement_timeout_count,
            baseline.statement_timeout_count,
        ),
        lock_timeout_delta_5m=_compute_delta(
            lock_timeout_count,
            baseline.lock_timeout_count,
        ),
        match_candidates=_table_health_from_row(
            "match_candidates",
            table_rows.get("match_candidates"),
            now=captured_at_dt,
        ),
        match_pairs=_table_health_from_row(
            "match_pairs",
            table_rows.get("match_pairs"),
            now=captured_at_dt,
        ),
    )


def collect_match_artifact_health_snapshot() -> MatchArtifactHealthSnapshot:
    try:
        db_snapshot = collect_match_artifact_db_snapshot()
    except Exception as exc:
        logger.warning("Failed to collect match artifact DB snapshot", exc_info=True)
        return _empty_snapshot(error=str(exc))

    snapshot = MatchArtifactHealthSnapshot(
        db_snapshot=db_snapshot,
        collector_ok=True,
        collector_error=None,
    )
    try:
        _persist_health_snapshot(snapshot)
    except Exception as exc:
        logger.warning("Failed to persist durable match artifact health snapshot", exc_info=True)
        return MatchArtifactHealthSnapshot(
            db_snapshot=db_snapshot,
            collector_ok=False,
            collector_error=str(exc),
        )
    return snapshot


def load_match_artifact_health_snapshot() -> MatchArtifactHealthSnapshot | None:
    try:
        with use_schema("public"), use_security_context(agency_id=None, is_superuser=True):
            with get_uow().session(is_superuser=True) as session:
                row = session.execute("""
                    SELECT
                        captured_at,
                        active_connections,
                        max_connections,
                        active_connection_ratio,
                        temp_bytes_total,
                        temp_bytes_delta_5m,
                        temp_files_total,
                        temp_files_delta_5m,
                        statement_timeout_count,
                        lock_timeout_count,
                        statement_timeout_delta_5m,
                        lock_timeout_delta_5m,
                        match_candidates_payload,
                        match_pairs_payload
                    FROM match_artifact_health_samples
                    ORDER BY captured_at DESC
                    LIMIT 1
                    """).fetchone()
    except Exception:
        logger.warning("Failed to load durable match artifact health snapshot", exc_info=True)
        return None
    if not row:
        return None
    try:
        return _snapshot_from_sample_row(dict(row))
    except Exception:
        logger.warning(
            "Failed to deserialize durable match artifact health snapshot", exc_info=True
        )
        return None


__all__ = [
    "MatchArtifactDbSnapshot",
    "MatchArtifactHealthSnapshot",
    "MatchArtifactTableHealth",
    "collect_match_artifact_db_snapshot",
    "collect_match_artifact_health_snapshot",
    "load_match_artifact_health_snapshot",
]
