from __future__ import annotations

from contextlib import contextmanager

from app.tests.server_tests._integration_auth_helpers import ensure_django
from server.api import tasks_match_pairs
from server.services import match_jobs

ensure_django()


class _Span:
    def set_attribute(self, *_args: object, **_kwargs: object) -> None:
        return None


@contextmanager
def _noop_span(*_args: object, **_kwargs: object):
    yield _Span()


@contextmanager
def _noop_context(*_args: object, **_kwargs: object):
    yield


@contextmanager
def _locked(*_args: object, **_kwargs: object):
    yield True


def test_flush_rebuild_demande_pairs_queue_drains_batches_and_reschedules(monkeypatch) -> None:
    drained_batches = [[11, 12, 13], [21, 22], []]
    scheduled_batches: list[tuple[tuple[object, ...], dict[str, object]]] = []
    rescheduled: list[dict[str, object]] = []
    cleared: list[int] = []

    monkeypatch.setattr(tasks_match_pairs, "business_span", _noop_span)
    monkeypatch.setattr(tasks_match_pairs, "match_compute_context", _noop_context)
    monkeypatch.setattr(tasks_match_pairs, "match_pairs_rebuild_lock", _locked)
    monkeypatch.setattr(tasks_match_pairs, "_demande_flush_max_batches", lambda: 4)
    monkeypatch.setattr(tasks_match_pairs, "_demande_enqueue_task_batch_size", lambda: 250)
    monkeypatch.setattr(tasks_match_pairs, "_demande_task_chunk_size", lambda: 1000)
    monkeypatch.setattr(
        match_jobs,
        "dequeue_demande_rebuild_batch",
        lambda *, agency_id, batch_size: drained_batches.pop(0),
    )
    monkeypatch.setattr(match_jobs, "count_pending_demande_rebuilds", lambda *, agency_id: 3)
    monkeypatch.setattr(
        match_jobs,
        "schedule_demande_rebuild_flush",
        lambda *, kwargs: rescheduled.append(kwargs.copy()) or True,
    )
    monkeypatch.setattr(
        match_jobs,
        "clear_demande_rebuild_flush",
        lambda *, agency_id: cleared.append(int(agency_id)),
    )
    monkeypatch.setattr(
        tasks_match_pairs.rebuild_match_pairs_for_demandes_batch,
        "apply_async",
        lambda *args, **kwargs: scheduled_batches.append((args, kwargs)),
    )

    result = tasks_match_pairs.flush_rebuild_demande_pairs_queue.run(
        schema="public",
        agency_id=9,
        correlation_id="corr-1",
        actor_id=7,
        actor_role="manager",
    )

    assert result["demande_ids"] == 5
    assert result["batches"] == 1
    assert result["remaining"] == 3
    assert len(scheduled_batches) == 1
    assert scheduled_batches[0][1]["args"] == ([11, 12, 13, 21, 22],)
    assert rescheduled and rescheduled[0]["agency_id"] == 9
    assert cleared == [9]


def test_enqueue_rebuild_demande_pairs_batch_queues_for_shared_flush(monkeypatch) -> None:
    queued: dict[str, object] = {}

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

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Uow:
        @staticmethod
        def transaction():
            return _Session()

    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _Uow())
    monkeypatch.setattr(match_jobs, "use_security_context", _noop_context)
    monkeypatch.setattr(
        match_jobs.match_rebuild_state,
        "request_rebuild_batch",
        lambda _session, **kwargs: [11, 12, 13],
    )
    monkeypatch.setattr(
        match_jobs,
        "_queue_demande_rebuild_requests",
        lambda demande_ids, *, kwargs: queued.update(
            {"demande_ids": list(demande_ids), "agency_id": kwargs["agency_id"]}
        )
        or True,
    )

    match_jobs.enqueue_rebuild_demande_pairs_batch([11, 12, 13, 13], agency_id=9)

    assert queued == {"demande_ids": [11, 12, 13], "agency_id": 9}


def test_enqueue_rebuild_offer_pairs_batch_uses_bulk_rebuild_request(monkeypatch) -> None:
    scheduled: list[list[int]] = []

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

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Uow:
        @staticmethod
        def transaction():
            return _Session()

    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _Uow())
    monkeypatch.setattr(match_jobs, "use_security_context", _noop_context)
    monkeypatch.setattr(match_jobs, "_demande_task_chunk_size", lambda: 2)
    monkeypatch.setattr(
        match_jobs.match_rebuild_state,
        "request_rebuild_batch",
        lambda _session, **kwargs: [41, 42, 43],
    )
    monkeypatch.setattr(
        match_jobs,
        "logger",
        type("_Logger", (), {"warning": staticmethod(lambda *_args, **_kwargs: None)})(),
    )
    monkeypatch.setattr(
        "server.api.tasks.rebuild_match_pairs_for_offers_batch.delay",
        lambda offer_ids, **_kwargs: scheduled.append(list(offer_ids)),
    )

    match_jobs.enqueue_rebuild_offer_pairs_batch([41, 42, 43, 43], agency_id=9)

    assert scheduled == [[41, 42], [43]]
