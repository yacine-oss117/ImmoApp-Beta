from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from server.services import postgres_match_health


def _table_row(*, live: int, dead: int, index_bytes: int) -> dict[str, object]:
    now = datetime.now(tz=UTC)
    return {
        "live_tuples": live,
        "dead_tuples": dead,
        "table_bytes": 1024,
        "index_bytes": index_bytes,
        "total_bytes": 2048,
        "last_autovacuum": now - timedelta(seconds=60),
        "autovacuum_count": 2,
        "last_autoanalyze": now - timedelta(seconds=30),
        "autoanalyze_count": 3,
    }


class _FakeCursor:
    def __init__(self, captured_at: datetime) -> None:
        self._captured_at = captured_at
        self._last_sql = ""
        self.description = [("captured_at",)]

    def execute(self, sql: str, _params=None) -> None:
        self._last_sql = sql

    def fetchone(self):
        if "CURRENT_TIMESTAMP" in self._last_sql:
            return (self._captured_at,)
        return None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeConnection:
    def __init__(self, captured_at: datetime) -> None:
        self._captured_at = captured_at

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._captured_at)


class _FakeSession:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def execute(self, _sql: str, _params=()):
        return self

    def fetchone(self) -> dict[str, object] | None:
        return dict(self._row) if self._row is not None else None


class _FakeUow:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def session(self, **_kwargs):
        row = self._row

        class _Manager:
            def __enter__(self_inner):
                return _FakeSession(row)

            def __exit__(self_inner, exc_type, exc, tb) -> bool:
                return False

        return _Manager()


def test_table_health_computes_index_bloat_and_lags() -> None:
    now = datetime.now(tz=UTC)
    row = {
        "live_tuples": 100,
        "dead_tuples": 25,
        "table_bytes": 4096,
        "index_bytes": 12000,
        "total_bytes": 16000,
        "last_autovacuum": now - timedelta(seconds=90),
        "autovacuum_count": 4,
        "last_autoanalyze": now - timedelta(seconds=45),
        "autoanalyze_count": 5,
    }

    payload = postgres_match_health._table_health_from_row("match_pairs", row, now=now)

    assert payload.dead_ratio == 0.2
    assert payload.index_bloat_estimate_bytes == 5600
    assert payload.vacuum_lag_seconds == 90
    assert payload.analyze_lag_seconds == 45


def test_collect_db_snapshot_uses_durable_baseline_deltas(monkeypatch) -> None:
    captured_at = datetime.now(tz=UTC)

    monkeypatch.setattr(
        postgres_match_health, "transaction", type("_T", (), {"atomic": staticmethod(nullcontext)})
    )
    monkeypatch.setattr(
        postgres_match_health,
        "connection",
        _FakeConnection(captured_at),
    )
    monkeypatch.setattr(postgres_match_health, "_load_connection_snapshot", lambda _cursor: (8, 10))
    monkeypatch.setattr(postgres_match_health, "_load_temp_counters", lambda _cursor: (200, 4))
    monkeypatch.setattr(postgres_match_health, "_load_timeout_counters", lambda _cursor: (7, 3))
    monkeypatch.setattr(
        postgres_match_health,
        "_load_table_rows",
        lambda _cursor: {
            "match_candidates": _table_row(live=100, dead=10, index_bytes=12000),
            "match_pairs": _table_row(live=200, dead=20, index_bytes=18000),
        },
    )
    monkeypatch.setattr(
        postgres_match_health,
        "_load_sample_baseline",
        lambda _cursor, *, captured_before: (
            postgres_match_health._HealthSampleBaseline(100, 1, 5, 2)
        ),
    )

    snapshot = postgres_match_health.collect_match_artifact_db_snapshot()

    assert snapshot.active_connection_ratio == 0.8
    assert snapshot.temp_bytes_delta_5m == 100
    assert snapshot.temp_files_delta_5m == 3
    assert snapshot.statement_timeout_delta_5m == 2
    assert snapshot.lock_timeout_delta_5m == 1
    assert snapshot.match_candidates.index_bloat_estimate_bytes == 5600


def test_collect_health_snapshot_persists_durable_sample(monkeypatch) -> None:
    db_snapshot = postgres_match_health.MatchArtifactDbSnapshot(
        captured_at=datetime.now(tz=UTC).isoformat(),
        active_connections=1,
        max_connections=10,
        active_connection_ratio=0.1,
        temp_bytes_total=200,
        temp_bytes_delta_5m=10,
        temp_files_total=3,
        temp_files_delta_5m=1,
        statement_timeout_count=7,
        lock_timeout_count=2,
        statement_timeout_delta_5m=1,
        lock_timeout_delta_5m=0,
        match_candidates=postgres_match_health._empty_table_health("match_candidates"),
        match_pairs=postgres_match_health._empty_table_health("match_pairs"),
    )
    stored: list[postgres_match_health.MatchArtifactHealthSnapshot] = []

    monkeypatch.setattr(
        postgres_match_health,
        "collect_match_artifact_db_snapshot",
        lambda: db_snapshot,
    )
    monkeypatch.setattr(
        postgres_match_health,
        "_persist_health_snapshot",
        lambda snapshot: stored.append(snapshot),
    )

    snapshot = postgres_match_health.collect_match_artifact_health_snapshot()

    assert snapshot.collector_ok is True
    assert snapshot.collector_error is None
    assert snapshot.db_snapshot.statement_timeout_count == 7
    assert len(stored) == 1
    assert stored[0].db_snapshot.captured_at == db_snapshot.captured_at


def test_collect_health_snapshot_reports_persistence_failure(monkeypatch) -> None:
    db_snapshot = postgres_match_health._empty_db_snapshot()

    monkeypatch.setattr(
        postgres_match_health,
        "collect_match_artifact_db_snapshot",
        lambda: db_snapshot,
    )
    monkeypatch.setattr(
        postgres_match_health,
        "_persist_health_snapshot",
        lambda _snapshot: (_ for _ in ()).throw(RuntimeError("persist failed")),
    )

    snapshot = postgres_match_health.collect_match_artifact_health_snapshot()

    assert snapshot.collector_ok is False
    assert snapshot.collector_error == "persist failed"
    assert snapshot.db_snapshot.captured_at == db_snapshot.captured_at


def test_load_health_snapshot_uses_durable_sample_store(monkeypatch) -> None:
    row = {
        "captured_at": "2026-03-30T12:00:00+00:00",
        "active_connections": 3,
        "max_connections": 10,
        "active_connection_ratio": 0.3,
        "temp_bytes_total": 500,
        "temp_bytes_delta_5m": 50,
        "temp_files_total": 6,
        "temp_files_delta_5m": 2,
        "statement_timeout_count": 11,
        "lock_timeout_count": 4,
        "statement_timeout_delta_5m": 3,
        "lock_timeout_delta_5m": 1,
        "match_candidates_payload": {"table_name": "match_candidates", "live_tuples": 10},
        "match_pairs_payload": {"table_name": "match_pairs", "live_tuples": 20},
    }

    monkeypatch.setattr(postgres_match_health, "use_schema", lambda _schema: nullcontext())
    monkeypatch.setattr(
        postgres_match_health,
        "use_security_context",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(postgres_match_health, "get_uow", lambda: _FakeUow(row))

    snapshot = postgres_match_health.load_match_artifact_health_snapshot()

    assert snapshot is not None
    assert snapshot.collector_ok is True
    assert snapshot.collector_error is None
    assert snapshot.db_snapshot.statement_timeout_delta_5m == 3
    assert snapshot.db_snapshot.lock_timeout_delta_5m == 1
