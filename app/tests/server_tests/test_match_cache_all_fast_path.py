from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace


class _SessionCtx:
    def __enter__(self):
        return SimpleNamespace()

    def __exit__(self, exc_type, exc, tb):
        return False


class _Uow:
    @staticmethod
    def session():
        return _SessionCtx()

    @staticmethod
    def transaction():
        return _SessionCtx()


def test_count_matches_all_clients_task_uses_full_cte_fast_path_for_small_tenant(
    monkeypatch,
) -> None:
    from server.api import tasks_match_cache as module

    monkeypatch.setattr(
        module, "require_agency_id", lambda agency_id, task_name: int(agency_id or 1)
    )
    monkeypatch.setattr(module, "match_compute_context", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(module, "_task_lease_owner", lambda _task: "lease-1")
    monkeypatch.setattr(
        module,
        "_acquire_checkpoint",
        lambda **kwargs: (module.task_scan_checkpoint.ScanCheckpoint(0, 0, 0), False),
    )
    monkeypatch.setattr(module, "count_active_clients", lambda _session: 4)
    monkeypatch.setattr(
        module.match_counter,
        "batch_count_all_clients_cte",
        lambda _session: {1: 2, 2: 1},
    )
    monkeypatch.setattr(
        module,
        "iter_active_client_batches",
        lambda *_args, **_kwargs: (_ for _ in ()),
    )
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _Uow())
    monkeypatch.setattr(
        module.tenant_work_lease,
        "release_stream_slot",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setenv("IMMOAPP_MATCH_CACHE_ALL_FULL_CTE_THRESHOLD", "10")

    result = module.count_matches_all_clients_task(agency_id=1)

    assert result == {"counts": {1: 2, 2: 1}, "has_more": False, "last_id": 0}


def test_count_matches_all_clients_task_skips_fast_path_after_checkpoint_progress(
    monkeypatch,
) -> None:
    from server.api import tasks_match_cache as module

    saved: list[tuple[int, int]] = []

    monkeypatch.setattr(
        module, "require_agency_id", lambda agency_id, task_name: int(agency_id or 1)
    )
    monkeypatch.setattr(module, "match_compute_context", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(module, "_task_lease_owner", lambda _task: "lease-2")
    monkeypatch.setattr(
        module,
        "_acquire_checkpoint",
        lambda **kwargs: (module.task_scan_checkpoint.ScanCheckpoint(5, 1, 0), True),
    )
    monkeypatch.setattr(module, "count_active_clients", lambda _session: 4)

    def _unexpected_full_cte(_session):
        raise AssertionError("full CTE fast path must not run after checkpoint progress")

    monkeypatch.setattr(module.match_counter, "batch_count_all_clients_cte", _unexpected_full_cte)
    monkeypatch.setattr(module, "iter_active_client_batches", lambda _session, **kwargs: [[6, 7]])
    monkeypatch.setattr(
        module.match_counter,
        "batch_count_clients_paginated",
        lambda _session, batch: {int(client_id): 1 for client_id in batch},
    )
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _Uow())
    monkeypatch.setattr(
        module.task_scan_checkpoint,
        "save_progress",
        lambda _tx, **kwargs: saved.append((kwargs["last_id"], kwargs["rows_processed"])),
    )
    monkeypatch.setattr(
        module.task_scan_checkpoint, "heartbeat_lease", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        module.task_scan_checkpoint, "release_lease", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        module.task_scan_checkpoint, "reset_progress", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        module.tenant_work_lease,
        "release_stream_slot",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setenv("IMMOAPP_MATCH_CACHE_ALL_FULL_CTE_THRESHOLD", "10")

    result = module.count_matches_all_clients_task(agency_id=1)

    assert result == {"counts": {6: 1, 7: 1}, "has_more": False, "last_id": 7}
    assert saved == [(7, 3)]
