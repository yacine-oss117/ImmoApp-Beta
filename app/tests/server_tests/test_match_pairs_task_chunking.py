from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

pytest.importorskip("cryptography", reason="match task chunking tests require server dependencies")


class _SessionCtx:
    def __enter__(self):
        return SimpleNamespace(
            execute=lambda *_args, **_kwargs: SimpleNamespace(
                fetchall=lambda: [
                    {"scope_id": 11, "generation": 0},
                    {"scope_id": 12, "generation": 0},
                ]
            )
        )

    def __exit__(self, exc_type, exc, tb):
        return False


class _TxCtx:
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
        return _TxCtx()


def test_rebuild_match_pairs_for_demandes_batch_uses_single_sql_call_under_threshold(
    monkeypatch,
) -> None:
    from server.api import tasks_match_pairs

    calls: list[list[int]] = []

    monkeypatch.setattr(
        tasks_match_pairs, "require_agency_id", lambda agency_id, task_name: int(agency_id or 1)
    )
    monkeypatch.setattr(
        tasks_match_pairs,
        "business_span",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(set_attribute=lambda *a, **k: None)),
    )
    monkeypatch.setattr(
        tasks_match_pairs, "match_compute_context", lambda *args, **kwargs: nullcontext()
    )
    monkeypatch.setattr(
        tasks_match_pairs, "match_pairs_rebuild_lock", lambda *args, **kwargs: nullcontext(True)
    )
    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _Uow())
    monkeypatch.setattr(tasks_match_pairs, "_demande_full_sql_threshold", lambda: 10)
    monkeypatch.setattr(
        tasks_match_pairs,
        "adaptive_batch_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("adaptive batch path should not be used under threshold")
        ),
    )
    monkeypatch.setattr(
        tasks_match_pairs,
        "compute_match_pairs_for_demandes",
        lambda _session, demande_ids, *, limit: calls.append(list(demande_ids)) or (7, 9),
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_rebuild_state,
        "complete_rebuild_batch",
        lambda _session, **kwargs: [],
    )

    result = tasks_match_pairs.rebuild_match_pairs_for_demandes_batch.run(
        [11, 12],
        agency_id=1,
    )

    assert calls == [[11, 12]]
    assert result["stored"] == 7
    assert result["total_candidates"] == 9


def test_compute_demande_chunks_batches_and_uses_direct_pipeline_over_threshold(
    monkeypatch,
) -> None:
    from server.api import match_pairs_compute, tasks_match_pairs

    direct_calls: list[list[int]] = []

    class _DirectTx:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _DirectUow:
        @staticmethod
        def transaction():
            return _DirectTx()

    monkeypatch.setenv("IMMOAPP_MATCH_BUILD_PIPELINE", "direct")
    monkeypatch.setattr(
        match_pairs_compute,
        "business_span",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(set_attribute=lambda *a, **k: None)),
    )
    monkeypatch.setattr(
        match_pairs_compute,
        "record_match_artifact_pipeline",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        match_pairs_compute,
        "record_match_pair_rebuild",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        match_pairs_compute.match_artifact_pipeline,
        "rebuild_match_artifacts_for_demandes",
        lambda _session, demande_ids, *, limit: direct_calls.append(list(demande_ids))
        or match_pairs_compute.match_artifact_pipeline.MatchArtifactBatchResult(
            candidate_total=len(demande_ids) * 10,
            ranked_total=len(demande_ids) * 10,
            pair_total=len(demande_ids) * 5,
            per_demande={
                int(demande_id): match_pairs_compute.match_artifact_pipeline.MatchArtifactCounts(
                    candidate_total=10,
                    ranked_total=10,
                    pair_total=5,
                )
                for demande_id in demande_ids
            },
        ),
    )
    monkeypatch.setattr(
        match_pairs_compute.match_candidates_data,
        "replace_candidates_for_demandes_from_match_query",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy path should not be used when direct mode is enabled")
        ),
    )
    monkeypatch.setattr(
        match_pairs_compute.match_pairs_data,
        "rebuild_pairs_for_demandes_from_candidates_sql",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy path should not be used when direct mode is enabled")
        ),
    )
    monkeypatch.setattr(tasks_match_pairs, "_demande_full_sql_threshold", lambda: 2)
    monkeypatch.setattr(tasks_match_pairs, "_demande_batch_size", lambda: 2)
    monkeypatch.setattr(
        tasks_match_pairs,
        "adaptive_batch_process",
        lambda items, process_fn, *, label: [process_fn(item) for item in items],
    )

    stored, candidates = tasks_match_pairs._compute_demande_chunks(
        get_uow=lambda: _DirectUow(),
        demande_ids=[11, 12, 13, 14, 15],
        limit=1,
        label="direct_chunk_test",
    )

    assert direct_calls == [[11, 12], [13, 14], [15]]
    assert stored == 25
    assert candidates == 50


def test_demande_rebuild_schedule_records_follow_up_when_flush_lock_exists(
    monkeypatch,
) -> None:
    from server.services import match_jobs

    class _Cache:
        def __init__(self) -> None:
            self.values: dict[str, object] = {match_jobs._demande_flush_lock_key(agency_id=7): "1"}

        def add(self, key: str, value: object, timeout: int | None = None) -> bool:
            if key in self.values:
                return False
            self.values[key] = value
            return True

        def set(self, key: str, value: object, timeout: int | None = None) -> None:
            self.values[key] = value

        def get(self, key: str) -> object | None:
            return self.values.get(key)

        def delete(self, key: str) -> None:
            self.values.pop(key, None)

    cache = _Cache()
    monkeypatch.setattr(match_jobs, "caches", {"default": cache})

    scheduled = match_jobs.schedule_demande_rebuild_flush(kwargs={"agency_id": 7})

    assert scheduled is False
    assert cache.get(match_jobs._demande_flush_requested_key(agency_id=7)) == "1"


def test_demande_flush_schedules_follow_up_when_marker_was_recorded(
    monkeypatch,
) -> None:
    from server.api import tasks_match_pairs

    scheduled: list[dict[str, object]] = []

    monkeypatch.setattr(
        tasks_match_pairs, "require_agency_id", lambda agency_id, task_name: int(agency_id or 1)
    )
    monkeypatch.setattr(
        tasks_match_pairs,
        "build_async_task_identity",
        lambda **kwargs: {key: value for key, value in kwargs.items() if value is not None},
    )
    monkeypatch.setattr(
        tasks_match_pairs,
        "business_span",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(set_attribute=lambda *a, **k: None)),
    )
    monkeypatch.setattr(
        tasks_match_pairs, "match_compute_context", lambda *args, **kwargs: nullcontext()
    )
    monkeypatch.setattr(
        tasks_match_pairs, "match_pairs_rebuild_lock", lambda *args, **kwargs: nullcontext(True)
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_jobs,
        "dequeue_demande_rebuild_batch",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_jobs,
        "clear_demande_rebuild_flush",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_jobs,
        "pop_demande_rebuild_flush_requested",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_jobs,
        "count_pending_demande_rebuilds",
        lambda **kwargs: 0,
    )
    monkeypatch.setattr(
        tasks_match_pairs.match_jobs,
        "schedule_demande_rebuild_flush",
        lambda **kwargs: scheduled.append(dict(kwargs["kwargs"])) or True,
    )

    result = tasks_match_pairs.flush_rebuild_demande_pairs_queue.run(agency_id=7)

    assert result["follow_up_requested"] is True
    assert scheduled == [{"agency_id": 7}]
