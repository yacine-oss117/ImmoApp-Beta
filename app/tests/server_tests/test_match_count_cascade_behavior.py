from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

pytest.importorskip(
    "cryptography", reason="match cascade behavior tests require server dependencies"
)


class _SessionCtx:
    def __init__(self, session: object) -> None:
        self._session = session

    def __enter__(self) -> object:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _TxCtx:
    def __init__(self, session: object | None = None) -> None:
        self._session = session if session is not None else SimpleNamespace()

    def __enter__(self) -> object:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _CommitSession(SimpleNamespace):
    def __init__(self) -> None:
        super().__init__()
        self.on_commit_callbacks: list[object] = []

    def on_commit(self, callback) -> None:
        self.on_commit_callbacks.append(callback)


class _CommitUow:
    def __init__(self, session: _CommitSession) -> None:
        self._session = session

    def transaction(self, *args, **kwargs) -> _SessionCtx:
        _ = args
        _ = kwargs
        return _SessionCtx(self._session)


class _StaticUow:
    def __init__(self, session: object | None = None) -> None:
        self._session = session if session is not None else SimpleNamespace()

    def session(self) -> _SessionCtx:
        return _SessionCtx(self._session)

    def transaction(self, *args, **kwargs) -> _TxCtx:
        _ = args
        _ = kwargs
        return _TxCtx()


def _patch_task_common(monkeypatch, module) -> None:
    monkeypatch.setattr(
        module, "require_agency_id", lambda agency_id, _task_name: int(agency_id or 1)
    )
    monkeypatch.setattr(
        module,
        "business_span",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(set_attribute=lambda *a, **k: None)),
    )
    monkeypatch.setattr(module, "match_compute_context", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        module, "match_pairs_rebuild_lock", lambda *args, **kwargs: nullcontext(True)
    )


@pytest.mark.parametrize(
    ("function_name", "kwargs", "extra_patch"),
    [
        (
            "rebuild_match_pairs_for_demande",
            {"demande_id": 41},
            lambda monkeypatch, module: monkeypatch.setattr(
                module,
                "compute_match_pairs_for_demande",
                lambda _session, demande_id, limit=None: (int(demande_id), 5),
            ),
        ),
        (
            "rebuild_match_pairs_for_client",
            {"client_id": 51},
            lambda monkeypatch, module: (
                monkeypatch.setattr(
                    module.demande_data,
                    "iter_demande_ids_for_client",
                    lambda _session, client_id, include_deleted=False, page_size=500: [[111, 112]],
                ),
                monkeypatch.setattr(module, "_compute_demande_chunks", lambda **kwargs: (7, 9)),
            ),
        ),
        (
            "rebuild_match_pairs_for_offer",
            {"offer_id": 61},
            lambda monkeypatch, module: (
                monkeypatch.setattr(
                    module.demande_data,
                    "get_demande_ids_for_offer",
                    lambda _session, offer_id: [121, 122],
                ),
                monkeypatch.setattr(
                    module.match_pairs_data,
                    "clear_pairs_for_offer",
                    lambda _session, offer_id: None,
                ),
                monkeypatch.setattr(
                    module.match_candidates_data,
                    "clear_candidates_for_offer",
                    lambda _session, offer_id: None,
                ),
                monkeypatch.setattr(module, "_compute_demande_chunks", lambda **kwargs: (8, 10)),
            ),
        ),
        (
            "rebuild_match_pairs_for_wilaya",
            {"wilaya_id": 71},
            lambda monkeypatch, module: (
                monkeypatch.setattr(
                    module, "resolve_wilaya_id", lambda _session, wilaya_id, wilaya=None: 71
                ),
                monkeypatch.setattr(
                    module.demande_data,
                    "iter_demande_ids_for_wilaya",
                    lambda _session, wilaya_id, page_size=500: [[131, 132]],
                ),
                monkeypatch.setattr(module, "_compute_demande_chunks", lambda **kwargs: (6, 12)),
            ),
        ),
    ],
)
def test_pair_rebuild_tasks_trigger_count_cache_cascade(
    monkeypatch,
    function_name: str,
    kwargs: dict[str, int],
    extra_patch,
) -> None:
    from server.api import tasks_match_cache, tasks_match_pairs

    _patch_task_common(monkeypatch, tasks_match_pairs)
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _StaticUow())
    monkeypatch.setattr(
        tasks_match_pairs.match_rebuild_state, "get_generation", lambda *_args, **_kwargs: 0
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_rebuild_state,
        "complete_rebuild",
        lambda *_args, **_kwargs: False,
    )
    extra_patch(monkeypatch, tasks_match_pairs)

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        tasks_match_cache,
        "rebuild_match_cache_dirty",
        SimpleNamespace(delay=lambda **delay_kwargs: calls.append(delay_kwargs)),
    )

    task = getattr(tasks_match_pairs, function_name)
    result = task.run(
        agency_id=7,
        correlation_id="corr-123",
        actor_id=91,
        actor_role="manager",
        **kwargs,
    )

    assert result
    assert calls == [
        {
            "schema": None,
            "agency_id": 7,
            "correlation_id": "corr-123",
            "actor_id": 91,
            "actor_role": "manager",
        }
    ]


class _DirtyRows:
    def __init__(self, rows: list[dict[str, int]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, int]]:
        return list(self._rows)


class _DirtySession:
    def __init__(self) -> None:
        self._dirty_calls = 0
        self._missing_calls = 0

    def execute(self, sql: str, params: tuple[object, ...]) -> _DirtyRows:
        if "FROM match_counts_cache" in sql and "WHERE is_dirty = 1" in sql:
            self._dirty_calls += 1
            if self._dirty_calls == 1:
                return _DirtyRows([{"client_id": 11}, {"client_id": 12}])
            return _DirtyRows([])
        if "LEFT JOIN match_counts_cache" in sql:
            self._missing_calls += 1
            if self._missing_calls == 1:
                return _DirtyRows([{"id": 21}])
            return _DirtyRows([])
        raise AssertionError(f"Unexpected SQL in dirty cache rebuild: {sql}")


class _DirtyUow:
    def __init__(self) -> None:
        self._session = _DirtySession()

    def session(self) -> _SessionCtx:
        return _SessionCtx(self._session)

    def transaction(self) -> _TxCtx:
        return _TxCtx()


def test_rebuild_match_cache_dirty_recomputes_dirty_and_missing_clients(monkeypatch) -> None:
    from server.api import tasks_match_cache

    monkeypatch.setattr(
        tasks_match_cache, "require_agency_id", lambda agency_id, _task_name: int(agency_id or 1)
    )
    monkeypatch.setattr(
        tasks_match_cache, "match_compute_context", lambda *args, **kwargs: nullcontext()
    )
    monkeypatch.setattr(
        tasks_match_cache, "match_cache_rebuild_lock", lambda *args, **kwargs: nullcontext(True)
    )
    monkeypatch.setattr(
        tasks_match_cache, "_mark_rebuild_task_running", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(tasks_match_cache, "_mark_rebuild_task_done", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tasks_match_cache, "_mark_rebuild_task_failed", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        tasks_match_cache,
        "adaptive_batch_process",
        lambda items, process_fn, *, batch_size=100, label="batch": [
            process_fn(item) for item in items
        ],
    )
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _DirtyUow())

    counted_batches: list[list[int]] = []
    labels: list[str] = []

    monkeypatch.setattr(
        tasks_match_cache.match_counter,
        "batch_count_clients_paginated",
        lambda _session, batch: counted_batches.append(list(batch))
        or {int(client_id): 1 for client_id in batch},
    )
    monkeypatch.setattr(
        tasks_match_cache,
        "store_counts",
        lambda _session, counts, *, label: labels.append(label) or len(counts),
    )

    result = tasks_match_cache.rebuild_match_cache_dirty.run(agency_id=3)

    assert counted_batches == [[11, 12], [21]]
    assert labels == ["dirty clients", "missing clients"]
    assert result == {"clients": 3, "dirty": 3}


def test_offer_rebuild_clears_stale_offer_pairs_before_recompute(monkeypatch) -> None:
    from server.api import tasks_match_cache, tasks_match_pairs

    _patch_task_common(monkeypatch, tasks_match_pairs)
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _StaticUow())
    monkeypatch.setattr(
        tasks_match_pairs.match_rebuild_state, "get_generation", lambda *_args, **_kwargs: 0
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_rebuild_state,
        "complete_rebuild",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        tasks_match_pairs.demande_data,
        "get_demande_ids_for_offer",
        lambda _session, offer_id: [121],
    )

    calls: list[str] = []
    monkeypatch.setattr(
        tasks_match_pairs.match_candidates_data,
        "clear_candidates_for_offer",
        lambda _session, offer_id: calls.append(f"clear_candidates:{offer_id}"),
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_pairs_data,
        "clear_pairs_for_offer",
        lambda _session, offer_id: calls.append(f"clear_pairs:{offer_id}"),
    )

    def _compute_chunks(**_kwargs) -> tuple[int, int]:
        calls.append("compute")
        return 0, 0

    monkeypatch.setattr(tasks_match_pairs, "_compute_demande_chunks", _compute_chunks)
    monkeypatch.setattr(
        tasks_match_cache,
        "rebuild_match_cache_dirty",
        SimpleNamespace(delay=lambda **_kwargs: calls.append("cascade")),
    )

    result = tasks_match_pairs.rebuild_match_pairs_for_offer.run(
        offer_id=61,
        agency_id=7,
        correlation_id="corr-123",
        actor_id=91,
        actor_role="manager",
    )

    assert result == {"offer_id": 61, "demande_ids": 1, "stored": 0}
    assert calls == ["clear_candidates:61", "clear_pairs:61", "compute", "cascade"]


def test_offer_rebuild_uses_stale_demande_hint_when_current_offer_is_incompatible(
    monkeypatch,
) -> None:
    from server.api import tasks_match_cache, tasks_match_pairs

    _patch_task_common(monkeypatch, tasks_match_pairs)
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _StaticUow())
    monkeypatch.setattr(
        tasks_match_pairs.match_rebuild_state, "get_generation", lambda *_args, **_kwargs: 0
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_rebuild_state,
        "complete_rebuild",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        tasks_match_pairs.demande_data,
        "get_demande_ids_for_offer",
        lambda _session, offer_id: [],
    )

    calls: list[str] = []
    computed_demande_ids: list[int] = []
    monkeypatch.setattr(
        tasks_match_pairs.match_candidates_data,
        "clear_candidates_for_offer",
        lambda _session, offer_id: calls.append(f"clear_candidates:{offer_id}"),
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_pairs_data,
        "clear_pairs_for_offer",
        lambda _session, offer_id: calls.append(f"clear_pairs:{offer_id}"),
    )

    def _compute_chunks(**kwargs) -> tuple[int, int]:
        computed_demande_ids.extend(kwargs["demande_ids"])
        calls.append("compute")
        return 0, 0

    monkeypatch.setattr(tasks_match_pairs, "_compute_demande_chunks", _compute_chunks)
    monkeypatch.setattr(
        tasks_match_cache,
        "rebuild_match_cache_dirty",
        SimpleNamespace(delay=lambda **_kwargs: calls.append("cascade")),
    )

    result = tasks_match_pairs.rebuild_match_pairs_for_offer.run(
        offer_id=61,
        demande_ids_hint=[121],
        agency_id=7,
        correlation_id="corr-123",
        actor_id=91,
        actor_role="manager",
    )

    assert result == {"offer_id": 61, "demande_ids": 1, "stored": 0}
    assert computed_demande_ids == [121]
    assert calls == ["clear_candidates:61", "clear_pairs:61", "compute", "cascade"]


def test_update_offer_incompatible_mutation_dirties_old_scope_and_rebuilds_old_demandes(
    monkeypatch,
) -> None:
    from core.models import Offer
    from server.services import offers

    session = _CommitSession()
    monkeypatch.setattr(offers, "get_uow", lambda: _CommitUow(session))
    existing = Offer(
        id=61,
        listing_id=4,
        type="apartment",
        type_id=1,
        action="sell",
        action_id=1,
        wilaya="Algiers",
        wilaya_id=16,
        location="Hydra",
        beds=3,
        surface=90.0,
        budget=250.0,
        floor=2,
    )
    updated = Offer(
        id=61,
        listing_id=4,
        type="house",
        type_id=2,
        action="sell",
        action_id=1,
        wilaya="Algiers",
        wilaya_id=16,
        location="Hydra",
        beds=3,
        surface=90.0,
        budget=250.0,
        floor=2,
    )
    offer_reads = [existing, updated]
    monkeypatch.setattr(
        offers.read,
        "get_offer_by_id",
        lambda *_args, **_kwargs: offer_reads.pop(0),
    )
    monkeypatch.setattr(
        offers.demande_repo_read,
        "get_demande_ids_from_precomputed_for_offer",
        lambda _session, offer_id: [101],
    )
    monkeypatch.setattr(
        offers.demande_repo_read,
        "get_demande_ids_for_offer",
        lambda _session, offer_id: [],
    )
    monkeypatch.setattr(
        offers,
        "resolve_lookup_fields",
        lambda _session, processed: {**processed, "type_id": 2, "action_id": 1, "wilaya_id": 16},
    )

    dirty_wilayas: list[int] = []
    dirty_demande_ids: list[list[int]] = []
    enqueued: list[tuple[int, list[int]]] = []
    monkeypatch.setattr(
        offers,
        "mark_clients_in_wilaya_dirty",
        lambda _session, wilaya_id: dirty_wilayas.append(int(wilaya_id)),
    )
    monkeypatch.setattr(
        offers,
        "mark_clients_for_demande_ids_dirty",
        lambda _session, demande_ids: dirty_demande_ids.append(list(demande_ids)),
    )
    monkeypatch.setattr(offers.write, "update_offer", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        offers,
        "enqueue_rebuild_offer_pairs",
        lambda offer_id, *, demande_ids_hint=None: enqueued.append(
            (int(offer_id), list(demande_ids_hint or []))
        ),
    )

    offers.update_offer(61, {"type": "house", "remarks": "incompatible"})
    for callback in session.on_commit_callbacks:
        callback()

    assert dirty_wilayas == [16]
    assert dirty_demande_ids == [[101]]
    assert enqueued == [(61, [101])]


def test_update_offer_between_wilayas_dirties_old_and_new_affected_scopes(monkeypatch) -> None:
    from core.models import Offer
    from server.services import offers

    session = _CommitSession()
    monkeypatch.setattr(offers, "get_uow", lambda: _CommitUow(session))
    existing = Offer(
        id=61,
        listing_id=4,
        type="apartment",
        type_id=1,
        action="sell",
        action_id=1,
        wilaya="Algiers",
        wilaya_id=16,
        location="Hydra",
        beds=3,
        surface=90.0,
        budget=250.0,
        floor=2,
    )
    updated = Offer(
        id=61,
        listing_id=4,
        type="apartment",
        type_id=1,
        action="sell",
        action_id=1,
        wilaya="Oran",
        wilaya_id=31,
        location="Bir El Djir",
        beds=3,
        surface=90.0,
        budget=250.0,
        floor=2,
    )
    offer_reads = [existing, updated]
    monkeypatch.setattr(
        offers.read,
        "get_offer_by_id",
        lambda *_args, **_kwargs: offer_reads.pop(0),
    )
    monkeypatch.setattr(
        offers.demande_repo_read,
        "get_demande_ids_from_precomputed_for_offer",
        lambda _session, offer_id: [101],
    )
    monkeypatch.setattr(
        offers.demande_repo_read,
        "get_demande_ids_for_offer",
        lambda _session, offer_id: [202],
    )
    monkeypatch.setattr(
        offers,
        "resolve_lookup_fields",
        lambda _session, processed: {**processed, "type_id": 1, "action_id": 1, "wilaya_id": 31},
    )

    dirty_wilayas: list[int] = []
    dirty_demande_ids: list[list[int]] = []
    enqueued: list[tuple[int, list[int]]] = []
    monkeypatch.setattr(
        offers,
        "mark_clients_in_wilaya_dirty",
        lambda _session, wilaya_id: dirty_wilayas.append(int(wilaya_id)),
    )
    monkeypatch.setattr(
        offers,
        "mark_clients_for_demande_ids_dirty",
        lambda _session, demande_ids: dirty_demande_ids.append(list(demande_ids)),
    )
    monkeypatch.setattr(offers.write, "update_offer", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        offers,
        "enqueue_rebuild_offer_pairs",
        lambda offer_id, *, demande_ids_hint=None: enqueued.append(
            (int(offer_id), list(demande_ids_hint or []))
        ),
    )

    offers.update_offer(61, {"wilaya": "Oran", "location": "Bir El Djir"})
    for callback in session.on_commit_callbacks:
        callback()

    assert dirty_wilayas == [16, 31]
    assert dirty_demande_ids == [[101, 202]]
    assert enqueued == [(61, [101, 202])]
