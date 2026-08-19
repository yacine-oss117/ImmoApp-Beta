from __future__ import annotations

import types
from typing import Any

from server import async_task_identity
from server.services import match_jobs, matches


def test_context_async_identity_uses_explicit_agency_when_context_missing(monkeypatch) -> None:
    monkeypatch.setattr(async_task_identity, "get_current_agency_id", lambda: None)
    monkeypatch.setattr(async_task_identity, "get_current_schema", lambda: "public")
    monkeypatch.setattr(async_task_identity, "get_current_actor_id", lambda: 101)
    monkeypatch.setattr(async_task_identity, "get_current_actor_role", lambda: "manager")
    monkeypatch.setattr(async_task_identity, "is_current_actor_owner", lambda: False)
    monkeypatch.setattr(async_task_identity, "get_correlation_id", lambda: "corr-1")

    payload = async_task_identity.build_context_async_task_identity(agency_id=9)

    assert payload is not None
    assert payload["agency_id"] == 9
    assert payload["schema"] == "public"
    assert payload["actor_id"] == 101
    assert payload["actor_role"] == "manager"
    assert payload["correlation_id"] == "corr-1"


def test_ensure_pairs_enqueued_derives_agency_for_superuser_context(monkeypatch) -> None:
    class _Rows:
        def __init__(self, row: dict[str, Any] | None) -> None:
            self._row = row

        def fetchone(self) -> dict[str, Any] | None:
            return self._row

    class _Session:
        def execute(self, _sql: str, _params: tuple[int]) -> _Rows:
            return _Rows({"agency_id": 7})

    captured: dict[str, int | None] = {"demande_id": None, "agency_id": None}

    def _capture_enqueue(demande_id: int, *, agency_id: int | None = None) -> None:
        captured["demande_id"] = demande_id
        captured["agency_id"] = agency_id

    monkeypatch.setattr(matches, "_MATCH_CACHE_ONLY", True)
    monkeypatch.setattr(matches, "_needs_pair_rebuild", lambda _session, _demande_id: True)
    monkeypatch.setattr(matches, "get_current_agency_id", lambda: None)
    monkeypatch.setattr(matches, "enqueue_rebuild_demande_pairs", _capture_enqueue)

    matches._ensure_pairs_enqueued(_Session(), 42)

    assert captured["demande_id"] == 42
    assert captured["agency_id"] == 7


def test_needs_pair_rebuild_true_when_only_stale_pairs_exist() -> None:
    class _Rows:
        def __init__(self, row: dict[str, Any] | None) -> None:
            self._row = row

        def fetchone(self) -> dict[str, Any] | None:
            return self._row

    class _Session:
        def execute(self, sql: str, _params: tuple[int]) -> _Rows:
            # Candidates exist.
            if "FROM match_candidates" in sql:
                return _Rows({"exists": 1})
            # No active pairs after ACTIVE_OFFER/ACTIVE_LISTING filtering.
            if "FROM match_pairs mp" in sql:
                return _Rows(None)
            raise AssertionError(f"Unexpected SQL in test: {sql}")

    assert matches._needs_pair_rebuild(_Session(), 158042) is True


def test_enqueue_rebuild_demande_pairs_records_with_effective_agency(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Tx:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(
        match_jobs,
        "_task_kwargs",
        lambda agency_id=None: {
            "schema": "public",
            "agency_id": int(agency_id or 0),
            "correlation_id": "corr-1",
            "actor_id": 1,
            "actor_role": "manager",
        },
    )
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: types.SimpleNamespace(transaction=_Tx))
    monkeypatch.setattr(
        match_jobs.match_rebuild_state,
        "request_rebuild",
        lambda _session, *, scope, scope_id, debounce_seconds=0: captured.update(
            {
                "scope": scope,
                "scope_id": scope_id,
                "debounce_seconds": debounce_seconds,
            }
        )
        or True,
    )
    monkeypatch.setattr(
        match_jobs,
        "schedule_demande_rebuild_flush",
        lambda *, kwargs: captured.update({"flush_kwargs": dict(kwargs)}) or True,
    )

    match_jobs.enqueue_rebuild_demande_pairs(77, agency_id=9)

    assert captured["scope"] == "demande"
    assert captured["scope_id"] == 77
    assert int(captured["debounce_seconds"]) >= 0
    assert captured["flush_kwargs"]["agency_id"] == 9


def test_enqueue_rebuild_demande_pairs_queues_for_batched_flush_when_cache_available(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {"scheduled": False}

    class _Tx:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(
        match_jobs,
        "_task_kwargs",
        lambda agency_id=None: {
            "schema": "public",
            "agency_id": int(agency_id or 0),
            "correlation_id": "corr-1",
            "actor_id": 1,
            "actor_role": "manager",
        },
    )
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: types.SimpleNamespace(transaction=_Tx))
    monkeypatch.setattr(
        match_jobs.match_rebuild_state,
        "request_rebuild",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        match_jobs,
        "schedule_demande_rebuild_flush",
        lambda *, kwargs: captured.__setitem__("scheduled", kwargs["agency_id"] == 9) or True,
    )

    match_jobs.enqueue_rebuild_demande_pairs(77, agency_id=9)

    assert captured["scheduled"] is True


def test_hydrate_pairs_inline_on_cache_miss_rebuilds(monkeypatch) -> None:
    class _Session:
        pass

    monkeypatch.setattr(matches, "_MATCH_CACHE_ONLY", True)
    monkeypatch.setattr(matches, "_needs_pair_rebuild", lambda _session, _demande_id: True)
    monkeypatch.setattr(
        matches.match_pairs_data,
        "rebuild_pairs_for_demande_from_candidates_sql",
        lambda _session, _demande_id, limit: (3, 3),
    )

    rebuilt = matches._hydrate_pairs_inline_on_cache_miss(_Session(), demande_id=99, limit=20)
    assert rebuilt is True


def test_hydrate_pairs_inline_on_cache_miss_rolls_back_on_error(monkeypatch) -> None:
    class _Session:
        def __init__(self) -> None:
            self.rolled_back = False

        def rollback(self) -> None:
            self.rolled_back = True

    session = _Session()
    monkeypatch.setattr(matches, "_MATCH_CACHE_ONLY", True)
    monkeypatch.setattr(matches, "_needs_pair_rebuild", lambda _session, _demande_id: True)

    def _raise(*_args: object, **_kwargs: object) -> tuple[int, int]:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        matches.match_pairs_data,
        "rebuild_pairs_for_demande_from_candidates_sql",
        _raise,
    )

    rebuilt = matches._hydrate_pairs_inline_on_cache_miss(session, demande_id=101, limit=20)
    assert rebuilt is False
    assert session.rolled_back is True
