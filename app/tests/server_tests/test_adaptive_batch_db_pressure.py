from __future__ import annotations

import types

from server.api import adaptive_batch


def test_system_load_ratio_prefers_db_pressure(monkeypatch) -> None:
    monkeypatch.setattr(adaptive_batch, "_cpu_load_ratio", lambda: 0.2)
    monkeypatch.setattr(adaptive_batch, "_db_pressure_ratio", lambda: 0.8)
    assert adaptive_batch._system_load_ratio() == 0.8


def test_system_load_ratio_preserves_cpu_backoff(monkeypatch) -> None:
    monkeypatch.setattr(adaptive_batch, "_cpu_load_ratio", lambda: 0.8)
    monkeypatch.setattr(adaptive_batch, "_db_pressure_ratio", lambda: 0.1)
    assert adaptive_batch._system_load_ratio() == 0.8


def test_system_load_ratio_stays_low_when_cpu_and_db_are_low(monkeypatch) -> None:
    monkeypatch.setattr(adaptive_batch, "_cpu_load_ratio", lambda: 0.2)
    monkeypatch.setattr(adaptive_batch, "_db_pressure_ratio", lambda: 0.1)
    assert adaptive_batch._system_load_ratio() == 0.2


def test_db_pressure_ratio_fails_open_on_query_error(monkeypatch) -> None:
    class _BrokenCursor:
        def __enter__(self):
            raise RuntimeError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(adaptive_batch, "_aimd_db_pressure_enabled", lambda: True)
    monkeypatch.setattr(adaptive_batch, "_db_pressure_cache_seconds", lambda: 0.0)
    monkeypatch.setattr(adaptive_batch, "_LAST_DB_PRESSURE", (0.0, 0.0))
    monkeypatch.setattr(
        adaptive_batch, "connection", types.SimpleNamespace(cursor=lambda: _BrokenCursor())
    )
    assert adaptive_batch._db_pressure_ratio() == 0.0


def test_db_pressure_ratio_uses_two_second_cache(monkeypatch) -> None:
    calls = {"count": 0}

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _sql):
            calls["count"] += 1

        def fetchone(self):
            return (8, 10)

    class _Connection:
        def cursor(self):
            return _Cursor()

    monotonic_values = iter([100.0, 101.0])
    monkeypatch.setattr(adaptive_batch, "_aimd_db_pressure_enabled", lambda: True)
    monkeypatch.setattr(adaptive_batch, "_db_pressure_cache_seconds", lambda: 2.0)
    monkeypatch.setattr(adaptive_batch, "_LAST_DB_PRESSURE", (0.0, 0.0))
    monkeypatch.setattr(adaptive_batch.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(adaptive_batch, "connection", _Connection())

    first = adaptive_batch._db_pressure_ratio()
    second = adaptive_batch._db_pressure_ratio()

    assert first == 0.8
    assert second == 0.8
    assert calls["count"] == 1
