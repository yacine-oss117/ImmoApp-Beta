from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

pytest.importorskip("cryptography", reason="match janitor tests require server dependencies")


class _JanitorRows:
    def __init__(
        self, *, fetchall_rows: list[dict[str, object]] | None = None, rowcount: int = 0
    ) -> None:
        self._fetchall_rows = fetchall_rows or []
        self.rowcount = rowcount

    def fetchall(self) -> list[dict[str, object]]:
        return list(self._fetchall_rows)


class _JanitorSession:
    def execute(
        self,
        sql: str,
        _params: tuple[object, ...] | tuple[int, ...] | None = None,
    ) -> _JanitorRows:
        if "SELECT d.id" in sql:
            return _JanitorRows(fetchall_rows=[{"id": 14}])
        if "DELETE FROM match_counts_cache" in sql:
            return _JanitorRows(rowcount=3)
        raise AssertionError(f"Unexpected janitor SQL: {sql}")


class _JanitorSessionCtx:
    def __enter__(self) -> _JanitorSession:
        return _JanitorSession()

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _JanitorUow:
    @staticmethod
    def session() -> _JanitorSessionCtx:
        return _JanitorSessionCtx()


class _AdminTx:
    def __enter__(self) -> SimpleNamespace:
        return SimpleNamespace()

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_match_pairs_janitor_batches_demande_work_instead_of_single_rebuilds(monkeypatch) -> None:
    from server.api import tasks_integrity

    batch_calls: list[tuple[str, list[int]]] = []
    single_calls: list[tuple[str, int]] = []
    cache_rebuilds: list[int] = []

    monkeypatch.setattr(
        tasks_integrity,
        "adaptive_batch_process",
        lambda items, fn, *, label: [fn(item) for item in items],
    )
    monkeypatch.setattr(
        tasks_integrity, "iter_active_agency_batches", lambda _session, batch_size: [[7]]
    )
    monkeypatch.setattr(
        tasks_integrity.match_rebuild_state,
        "fetch_stale_pending",
        lambda _session, **kwargs: [
            {"scope": "demande", "scope_id": 11},
            {"scope": "demande", "scope_id": 12},
            {"scope": "client", "scope_id": 22},
        ],
    )
    monkeypatch.setattr(
        tasks_integrity.match_rebuild_state,
        "reclaim_expired_dispatch_claims",
        lambda _session, *, scope, limit=200: 0,
    )
    monkeypatch.setattr(
        tasks_integrity.match_pairs_data,
        "find_demande_ids_missing_pairs",
        lambda _session, limit: [13],
    )
    monkeypatch.setattr(tasks_integrity.match_cache_read, "get_dirty_count", lambda _session: 1)
    monkeypatch.setattr(
        tasks_integrity,
        "_schedule_demande_rebuilds_batch",
        lambda *, demande_ids, agency_id, schema, correlation_id: batch_calls.append(
            (str(correlation_id), list(demande_ids))
        )
        or len(demande_ids),
    )
    monkeypatch.setattr(
        tasks_integrity,
        "_schedule_rebuild",
        lambda *, scope, scope_id, agency_id, schema, correlation_id: single_calls.append(
            (str(scope), int(scope_id))
        )
        or True,
    )
    monkeypatch.setattr("server.pg.uow.admin_transaction", lambda: _AdminTx())
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _JanitorUow())
    monkeypatch.setattr("server.pg.uow.use_security_context", lambda **kwargs: nullcontext())
    monkeypatch.setattr("server.pg.uow.get_current_schema", lambda: "public")
    monkeypatch.setattr(
        "server.api.tasks_match_cache.rebuild_match_cache_dirty",
        SimpleNamespace(delay=lambda **kwargs: cache_rebuilds.append(int(kwargs["agency_id"]))),
    )

    result = tasks_integrity.match_pairs_janitor_task.run()

    assert batch_calls == [
        ("janitor:pending", [11, 12]),
        ("janitor:missing", [13]),
        ("janitor:cold", [14]),
    ]
    assert single_calls == [("client", 22)]
    assert cache_rebuilds == [7]
    assert result["pending"] == 3
    assert result["missing"] == 1
    assert result["cold"] == 1
    assert result["scheduled"] == 5
