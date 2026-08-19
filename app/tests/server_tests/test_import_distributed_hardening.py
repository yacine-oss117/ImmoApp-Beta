from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from core.contracts.import_batch_refs import CreatedRowRef  # noqa: E402
from server.api import tasks_import_phase_tasks  # noqa: E402
from server.imports.models import ImportChunk, ImportChunkPhase, ImportJob  # noqa: E402
from server.services import import_distributed_execution as distributed_execution  # noqa: E402
from server.services.import_distributed_execution import (  # noqa: E402
    _flush_root_batch_with_conflict_isolation,
    load_chunk_phase,
    plan_chunk_phase,
)
from server.services.import_distributed_execution import (  # noqa: E402
    _is_unique_violation as distributed_is_unique_violation,
)
from server.services.import_load_conflict_isolation import (  # noqa: E402
    _flush_bundle_root_entries_with_conflict_isolation,
)
from server.services.import_load_policy import (  # noqa: E402
    is_unique_violation as bundle_is_unique_violation,
)
from server.services.import_load_service import (  # noqa: E402
    ImportLoadConsistencyError,
    load_same_side_bundle_import,
)
from server.services.import_phase_attempts import (  # noqa: E402
    ImportPhaseAttemptCancelled,
    StaleImportPhaseLeaseError,
)
from server.services.import_types import (  # noqa: E402
    ImportLoadOutcome,
    ImportResult,
    PreparedImportArtifact,
)


class _FakeTransactionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    def __enter__(self) -> object:
        return self._session

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        _ = (exc_type, exc, tb)
        return False


class _FakeUow:
    def __init__(self, session: object) -> None:
        self._session = session

    def transaction(self, **_kwargs: object) -> _FakeTransactionContext:
        return _FakeTransactionContext(self._session)


class _RecordingContext:
    def __init__(self, name: str, session: object, events: list[str]) -> None:
        self._name = name
        self._session = session
        self._events = events

    def __enter__(self) -> object:
        self._events.append(f"enter:{self._name}")
        return self._session

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        _ = (exc_type, exc, tb)
        self._events.append(f"exit:{self._name}")
        return False


class _RecordingLoadSession:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def execute(self, sql: str, params: object = ()) -> _FakeQueryResult:
        _ = sql
        self._events.append("query:precheck")
        if isinstance(params, tuple) and len(params) == 2:
            if params[1] == ImportChunk.Role.ROOT:
                return _FakeQueryResult([{"id": 501}])
            if params[1] == ImportChunkPhase.Phase.LOAD:
                return _FakeQueryResult(
                    [{"chunk_id": 501, "status": ImportChunkPhase.Status.COMPLETED}]
                )
        return _FakeQueryResult([])


class _RecordingUow:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def session(self, **_kwargs: object) -> _RecordingContext:
        return _RecordingContext("session", _RecordingLoadSession(self._events), self._events)

    def transaction(self, **_kwargs: object) -> _RecordingContext:
        return _RecordingContext("transaction", object(), self._events)


class _FakeQueryResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = list(rows)

    def fetchall(self) -> list[dict[str, object]]:
        return list(self._rows)


class _FakeLoadSession:
    def execute(self, _sql: str, params: object = ()) -> _FakeQueryResult:
        if isinstance(params, tuple) and len(params) == 2:
            if params[1] == ImportChunk.Role.ROOT:
                return _FakeQueryResult([{"id": 501}])
            if params[1] == ImportChunkPhase.Phase.LOAD:
                return _FakeQueryResult(
                    [{"chunk_id": 501, "status": ImportChunkPhase.Status.COMPLETED}]
                )
        return _FakeQueryResult([])


class _MutableError(RuntimeError):
    pass


class _SqlStateError(RuntimeError):
    def __init__(self, message: str, *, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class _UniqueViolation(RuntimeError):
    sqlstate = "23505"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "\n".join(json.dumps(row) for row in rows)
    path.write_text(payload, encoding="utf-8")


def _bundle_artifact(
    *,
    tmp_path: Path,
    root_rows: list[dict[str, Any]],
    child_rows: list[dict[str, Any]],
    current_batch_size: int = 10,
) -> PreparedImportArtifact:
    planned_root_path = tmp_path / "planned-root.jsonl"
    planned_child_path = tmp_path / "planned-child.jsonl"
    _write_jsonl(planned_root_path, root_rows)
    _write_jsonl(planned_child_path, child_rows)
    return PreparedImportArtifact(
        bundle_mode="same_side_bundle",
        total_rows=len(root_rows) + len(child_rows),
        current_batch_size=current_batch_size,
        chunks_total=max(1, len(root_rows) + len(child_rows)),
        planned_root_entries_path=planned_root_path,
        planned_child_entries_path=planned_child_path,
        root_entity="client",
        child_entity="demande",
        root_row_count=len(root_rows),
        child_row_count=len(child_rows),
    )


def _child_entry(*, row: int, anchor_id: int) -> dict[str, Any]:
    return {
        "row": row,
        "data": {"remarks": f"child-{row}"},
        "original": {"remarks": f"child-{row}"},
        "anchor_id": anchor_id,
        "anchor_key": "",
    }


def _run_distributed_child_load(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    child_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    planned_path = tmp_path / "distributed-planned-child.jsonl"
    _write_jsonl(planned_path, child_rows)
    persisted_rows: list[dict[str, Any]] = []
    phase = SimpleNamespace(
        id=41,
        lease_token="lease-child",
        chunk=SimpleNamespace(
            id=91,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            job=SimpleNamespace(id="job-distributed-child"),
        ),
    )

    monkeypatch.setattr(
        "server.services.import_distributed_execution.manifest_for_chunk",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.load_manifest_to_temp",
        lambda _manifest: planned_path,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.get_uow",
        lambda: _FakeUow(_FakeLoadSession()),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._adaptive_inner_batch_size",
        lambda _count: 10,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._require_phase_lease",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.is_phase_attempt_current",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.run_with_phase_attempt_fence",
        lambda **kwargs: kwargs["fn"](),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._is_cancel_requested",
        lambda _job: False,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._root_load_anchor_map",
        lambda _job: {},
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._publish_tripwire_from_db_time",
        lambda _db_time: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._cleanup_temp_path",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._persist_load_errors",
        lambda **kwargs: persisted_rows.extend(list(kwargs.get("rows", []))),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.insert_batch",
        lambda *, batch_rows, **_kwargs: [3000 + index for index, _ in enumerate(batch_rows)],
    )

    return load_chunk_phase(phase=phase, user_id=1), persisted_rows


def test_is_cancel_requested_throttles_refreshes_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeJob:
        def __init__(self) -> None:
            self.id = "job-cancel-cache"
            self.status = ImportJob.Status.RUNNING
            self.result_summary: dict[str, object] = {}
            self.refresh_calls = 0

        def refresh_from_db(self, *, fields: list[str]) -> None:
            assert fields == ["status", "result_summary"]
            self.refresh_calls += 1

    distributed_execution._clear_cancel_check_cache()
    try:
        monotonic_values = iter([0.0, 0.1, 0.8])
        monkeypatch.setattr(
            "server.services.import_distributed_execution._LEGACY_MONOTONIC",
            lambda: next(monotonic_values),
        )
        monkeypatch.setattr(
            "server.services.import_distributed_execution.workflow_payload",
            lambda _job: {},
        )

        job = _FakeJob()

        assert distributed_execution._is_cancel_requested(job) is False
        assert distributed_execution._is_cancel_requested(job) is False
        assert distributed_execution._is_cancel_requested(job) is False
        assert job.refresh_calls == 2
    finally:
        distributed_execution._clear_cancel_check_cache()


def test_cancel_requested_stays_sticky_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeJob:
        def __init__(self) -> None:
            self.id = "job-cancel-sticky"
            self.status = ImportJob.Status.RUNNING
            self.result_summary: dict[str, object] = {}
            self.refresh_calls = 0

        def refresh_from_db(self, *, fields: list[str]) -> None:
            assert fields == ["status", "result_summary"]
            self.refresh_calls += 1

    distributed_execution._clear_cancel_check_cache()
    try:
        monotonic_values = iter([0.0, 9.0])
        monkeypatch.setattr(
            "server.services.import_distributed_execution._LEGACY_MONOTONIC",
            lambda: next(monotonic_values),
        )
        monkeypatch.setattr(
            "server.services.import_distributed_execution.workflow_payload",
            lambda _job: {"cancel_requested": True},
        )

        job = _FakeJob()

        assert distributed_execution._is_cancel_requested(job) is True
        assert distributed_execution._is_cancel_requested(job) is True
        assert job.refresh_calls == 1
    finally:
        distributed_execution._clear_cancel_check_cache()


def test_distributed_plan_cancel_before_artifact_persistence_is_not_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared_path = tmp_path / "prepared-empty.jsonl"
    _write_jsonl(prepared_path, [])
    cleaned: list[object] = []
    phase = SimpleNamespace(
        id=51,
        lease_token="lease-plan-cancel",
        phase=ImportChunkPhase.Phase.PLAN,
        task_id="task-plan-cancel",
        chunk=SimpleNamespace(
            id=151,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            job=SimpleNamespace(
                id="job-plan-cancel",
                agency_id=1,
                status=ImportJob.Status.RUNNING,
            ),
        ),
    )

    monkeypatch.setattr(
        "server.services.import_distributed_execution.manifest_for_chunk",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.load_manifest_to_temp",
        lambda _manifest: prepared_path,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.get_uow",
        lambda: _RecordingUow([]),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.workflow_payload",
        lambda _job: {"params": {}},
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._is_cancel_requested",
        lambda _job: True,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._cleanup_temp_path",
        lambda path: cleaned.append(path),
    )

    with pytest.raises(ImportPhaseAttemptCancelled):
        plan_chunk_phase(phase=phase, user_id=1)

    assert cleaned


def test_distributed_load_cancel_before_apply_is_not_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_path = tmp_path / "planned-empty.jsonl"
    _write_jsonl(planned_path, [])
    cleaned: list[object] = []
    phase = SimpleNamespace(
        id=52,
        lease_token="lease-load-cancel",
        phase=ImportChunkPhase.Phase.LOAD,
        task_id="task-load-cancel",
        chunk=SimpleNamespace(
            id=152,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            job=SimpleNamespace(id="job-load-cancel", status=ImportJob.Status.RUNNING),
        ),
    )

    monkeypatch.setattr(
        "server.services.import_distributed_execution.manifest_for_chunk",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.load_manifest_to_temp",
        lambda _manifest: planned_path,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._is_cancel_requested",
        lambda _job: True,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._cleanup_temp_path",
        lambda path: cleaned.append(path),
    )

    with pytest.raises(ImportPhaseAttemptCancelled):
        load_chunk_phase(phase=phase, user_id=1)

    assert cleaned == [planned_path]


def test_distributed_load_cancel_mid_chunk_is_not_success_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_path = tmp_path / "planned-one.jsonl"
    _write_jsonl(planned_path, [{"row": 1, "data": {"family_name": "A"}}])
    cancel_checks = iter([False, True])
    insert_calls: list[object] = []
    phase = SimpleNamespace(
        id=53,
        lease_token="lease-load-mid-cancel",
        phase=ImportChunkPhase.Phase.LOAD,
        task_id="task-load-mid-cancel",
        chunk=SimpleNamespace(
            id=153,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            job=SimpleNamespace(id="job-load-mid-cancel", status=ImportJob.Status.RUNNING),
        ),
    )

    monkeypatch.setattr(
        "server.services.import_distributed_execution.manifest_for_chunk",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.load_manifest_to_temp",
        lambda _manifest: planned_path,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.get_uow",
        lambda: _FakeUow(_FakeLoadSession()),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._adaptive_inner_batch_size",
        lambda _count: 10,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._require_phase_lease",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._is_cancel_requested",
        lambda _job: next(cancel_checks),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._cleanup_temp_path",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.timed_insert_batch_rows",
        lambda **kwargs: insert_calls.append(kwargs),
    )

    with pytest.raises(ImportPhaseAttemptCancelled):
        load_chunk_phase(phase=phase, user_id=1)

    assert insert_calls == []


def _run_fake_chunk_phase_task(
    *,
    monkeypatch: pytest.MonkeyPatch,
    runner: Callable[[object, int], dict[str, Any]],
    cancel_result: bool = True,
    complete_result: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    calls: list[str] = []
    job = SimpleNamespace(id="job-phase-cancel")
    phase = SimpleNamespace(id=54, lease_token="lease-phase-cancel")

    monkeypatch.setattr(
        tasks_import_phase_tasks,
        "load_import_user",
        lambda _user_id: SimpleNamespace(id=1, role="manager", is_owner=False),
    )
    monkeypatch.setattr(
        tasks_import_phase_tasks,
        "load_import_service",
        lambda _user_id: SimpleNamespace(get_job=lambda _session_id: job),
    )
    monkeypatch.setattr(
        tasks_import_phase_tasks,
        "claim_phase_attempt_started",
        lambda **_kwargs: phase,
    )
    monkeypatch.setattr(
        tasks_import_phase_tasks,
        "complete_phase_attempt",
        lambda **_kwargs: calls.append("complete") or complete_result,
    )
    monkeypatch.setattr(
        tasks_import_phase_tasks,
        "cancel_phase_attempt",
        lambda **_kwargs: calls.append("cancel") or cancel_result,
    )
    monkeypatch.setattr(
        tasks_import_phase_tasks,
        "handle_phase_exception",
        lambda **_kwargs: calls.append("failure"),
    )

    result = tasks_import_phase_tasks._run_chunk_phase_task(
        _task=SimpleNamespace(request=SimpleNamespace(id="task-phase-cancel")),
        session_id="job-phase-cancel",
        user_id=1,
        agency_id=1,
        phase_id=54,
        schema=None,
        correlation_id=None,
        phase_name="import_plan_chunk_task",
        runner=runner,
        queue_import_dispatch_fn=lambda **_kwargs: calls.append("dispatch"),
    )
    return result, calls


def test_chunk_phase_task_cancel_true_returns_cancelled_without_complete_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_cancelled(_phase: object, _user_id: int) -> dict[str, Any]:
        raise ImportPhaseAttemptCancelled("cancelled")

    result, calls = _run_fake_chunk_phase_task(
        monkeypatch=monkeypatch,
        runner=_raise_cancelled,
        cancel_result=True,
    )

    assert result["status"] == "cancelled"
    assert calls == ["cancel"]


def test_chunk_phase_task_cancel_false_returns_stale_without_complete_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_cancelled(_phase: object, _user_id: int) -> dict[str, Any]:
        raise ImportPhaseAttemptCancelled("cancelled")

    result, calls = _run_fake_chunk_phase_task(
        monkeypatch=monkeypatch,
        runner=_raise_cancelled,
        cancel_result=False,
    )

    assert result["status"] == "stale"
    assert calls == ["cancel"]


def test_chunk_phase_task_stale_runner_does_not_complete_cancel_dispatch_or_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_stale(_phase: object, _user_id: int) -> dict[str, Any]:
        raise StaleImportPhaseLeaseError("stale")

    result, calls = _run_fake_chunk_phase_task(
        monkeypatch=monkeypatch,
        runner=_raise_stale,
    )

    assert result["status"] == "stale"
    assert calls == []


def test_chunk_phase_task_success_completes_and_dispatches_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _succeed(_phase: object, _user_id: int) -> dict[str, Any]:
        return {"processed_count": 1}

    result, calls = _run_fake_chunk_phase_task(
        monkeypatch=monkeypatch,
        runner=_succeed,
    )

    assert result["status"] == "completed"
    assert calls == ["complete", "dispatch"]


def test_load_child_prechecks_root_status_before_write_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_path = tmp_path / "distributed-precheck-child.jsonl"
    _write_jsonl(planned_path, [_child_entry(row=1, anchor_id=10)])
    events: list[str] = []
    phase = SimpleNamespace(
        id=42,
        lease_token="lease-precheck",
        chunk=SimpleNamespace(
            id=92,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            job=SimpleNamespace(id="job-precheck-child"),
        ),
    )

    monkeypatch.setattr(
        "server.services.import_distributed_execution.manifest_for_chunk",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.load_manifest_to_temp",
        lambda _manifest: planned_path,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.get_uow",
        lambda: _RecordingUow(events),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._adaptive_inner_batch_size",
        lambda _count: 10,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._require_phase_lease",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.is_phase_attempt_current",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.run_with_phase_attempt_fence",
        lambda **kwargs: kwargs["fn"](),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._is_cancel_requested",
        lambda _job: False,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._root_load_anchor_map",
        lambda _job: {},
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._publish_tripwire_from_db_time",
        lambda _db_time: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._cleanup_temp_path",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._persist_load_errors",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.timed_insert_batch_rows",
        lambda **_kwargs: SimpleNamespace(created_ids=[7001], db_duration=0.1),
    )

    result = load_chunk_phase(phase=phase, user_id=1)

    assert result["created_count"] == 1
    assert events == [
        "enter:session",
        "query:precheck",
        "query:precheck",
        "exit:session",
        "enter:transaction",
        "exit:transaction",
    ]


@pytest.mark.parametrize(
    ("checker", "module_path"),
    [
        (distributed_is_unique_violation, "distributed"),
        (bundle_is_unique_violation, "bundle"),
    ],
)
def test_is_unique_violation_only_accepts_sqlstate_23505(
    checker,
    module_path: str,
) -> None:
    del module_path
    duplicate_text_fk = _SqlStateError(
        "duplicate key value violates unique constraint", sqlstate="23503"
    )
    no_sqlstate_duplicate = RuntimeError("duplicate key value violates unique constraint")
    wrapped = _MutableError("outer duplicate wrapper")
    wrapped.__cause__ = _SqlStateError("inner unique violation", sqlstate="23505")
    wrapped_orig = _MutableError("outer orig wrapper")
    wrapped_orig.orig = SimpleNamespace(sqlstate="23505")

    assert checker(_SqlStateError("unique violation", sqlstate="23505")) is True
    assert checker(wrapped) is True
    assert checker(wrapped_orig) is True
    assert checker(duplicate_text_fk) is False
    assert checker(no_sqlstate_duplicate) is False


def test_distributed_conflict_isolation_includes_failed_attempt_db_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_values = iter([0.0, 1.0, 1.5, 2.0, 2.5, 3.0])
    monkeypatch.setattr(
        "server.services.import_distributed_execution.time.monotonic",
        lambda: next(monotonic_values),
    )

    def _fake_insert_batch_refs(
        *,
        batch_rows: list[dict[str, Any]],
        source_ordinals: list[int] | None = None,
        **_kwargs: object,
    ) -> list[CreatedRowRef]:
        if len(batch_rows) > 1:
            raise _UniqueViolation("root batch conflict")
        ordinal = 0 if not source_ordinals else int(source_ordinals[0])
        return [
            CreatedRowRef(
                source_ordinal=ordinal,
                created_id=9000 + int(str(batch_rows[0].get("phone", "0"))[-1]),
            )
        ]

    monkeypatch.setattr(
        "server.services.import_distributed_execution.insert_batch_refs", _fake_insert_batch_refs
    )

    created, skipped, db_time = _flush_root_batch_with_conflict_isolation(
        write_session=object(),
        entity_type="client",
        batch_entries=[
            {
                "row": 1,
                "data": {"phone": "0555001001"},
                "anchor_keys": ["phone:0555001001"],
            },
            {
                "row": 2,
                "data": {"phone": "0555001002"},
                "anchor_keys": ["phone:0555001002"],
            },
        ],
        load_outcome=ImportLoadOutcome(),
        created_anchor_map={},
        load_errors=[],
    )

    assert created == 2
    assert skipped == 0
    assert db_time == pytest.approx(2.0)


def test_bundle_conflict_isolation_includes_failed_attempt_db_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_values = iter([0.0, 1.0, 1.5, 2.0, 2.5, 3.0])
    monkeypatch.setattr(
        "server.services.import_load_policy.time.monotonic",
        lambda: next(monotonic_values),
    )

    def _fake_insert_batch_refs(
        *,
        batch_rows: list[dict[str, Any]],
        source_ordinals: list[int] | None = None,
        **_kwargs: object,
    ) -> list[CreatedRowRef]:
        if len(batch_rows) > 1:
            raise _UniqueViolation("root batch conflict")
        ordinal = 0 if not source_ordinals else int(source_ordinals[0])
        return [
            CreatedRowRef(
                source_ordinal=ordinal,
                created_id=9100 + int(str(batch_rows[0].get("phone", "0"))[-1]),
            )
        ]

    monkeypatch.setattr(
        "server.services.import_load_conflict_isolation.insert_batch_refs",
        _fake_insert_batch_refs,
    )

    batch_ids, db_time = _flush_bundle_root_entries_with_conflict_isolation(
        write_session=object(),
        entity_type="client",
        batch_entries=[
            {
                "row": 1,
                "data": {"phone": "0555001001"},
                "anchor_keys": ["phone:0555001001"],
            },
            {
                "row": 2,
                "data": {"phone": "0555001002"},
                "anchor_keys": ["phone:0555001002"],
            },
        ],
        imported_ids=[],
        load_outcome=ImportLoadOutcome(),
        created_anchor_map={},
        load_errors=[],
    )

    assert batch_ids == [9101, 9102]
    assert db_time == pytest.approx(2.0)


def test_load_same_side_bundle_allows_child_orphans_at_ten_percent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _bundle_artifact(
        tmp_path=tmp_path,
        root_rows=[],
        child_rows=[_child_entry(row=index, anchor_id=index) for index in range(1, 10)]
        + [_child_entry(row=10, anchor_id=0)],
    )
    result = ImportResult(success=False)
    errors: list[dict[str, Any]] = []

    monkeypatch.setattr("server.services.import_load_service.get_uow", lambda: _FakeUow(object()))
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_bundle_after_commit",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_load_service.insert_batch",
        lambda *, batch_rows, **_kwargs: [1000 + index for index, _row in enumerate(batch_rows)],
    )

    outcome = load_same_side_bundle_import(
        job=SimpleNamespace(id="job-child-threshold", agency_id=1),
        user_id=1,
        review_rows=[],
        errors=errors,
        result=result,
        artifact=artifact,
    )

    assert result.success is True
    assert result.created_count == 9
    assert result.error_count == 1
    assert result.skipped_count == 0
    assert len(result.created_ids) == 9
    assert errors == [
        {
            "row": 10,
            "errors": ["Planned child row lost its parent anchor during load."],
        }
    ]
    assert outcome.committed_entities == {"demande"}


def test_load_same_side_bundle_allows_when_child_orphan_count_is_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _bundle_artifact(
        tmp_path=tmp_path,
        root_rows=[],
        child_rows=[_child_entry(row=index, anchor_id=index) for index in range(1, 11)],
    )
    result = ImportResult(success=False)
    errors: list[dict[str, Any]] = []

    monkeypatch.setattr("server.services.import_load_service.get_uow", lambda: _FakeUow(object()))
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_bundle_after_commit",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_load_service.insert_batch",
        lambda *, batch_rows, **_kwargs: [2000 + index for index, _row in enumerate(batch_rows)],
    )

    outcome = load_same_side_bundle_import(
        job=SimpleNamespace(id="job-child-zero-threshold", agency_id=1),
        user_id=1,
        review_rows=[],
        errors=errors,
        result=result,
        artifact=artifact,
    )

    assert result.success is True
    assert result.created_count == 10
    assert result.error_count == 0
    assert result.skipped_count == 0
    assert errors == []
    assert outcome.committed_entities == {"demande"}


def test_load_same_side_bundle_raises_when_child_orphans_exceed_ten_percent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _bundle_artifact(
        tmp_path=tmp_path,
        root_rows=[],
        child_rows=[_child_entry(row=index, anchor_id=index) for index in range(1, 9)]
        + [_child_entry(row=9, anchor_id=0), _child_entry(row=10, anchor_id=0)],
    )
    result = ImportResult(success=False)
    errors: list[dict[str, Any]] = []

    monkeypatch.setattr("server.services.import_load_service.get_uow", lambda: _FakeUow(object()))
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_bundle_after_commit",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_load_service.insert_batch",
        lambda *, batch_rows, **_kwargs: [1100 + index for index, _row in enumerate(batch_rows)],
    )

    with pytest.raises(
        ImportLoadConsistencyError,
        match="significant number of planned lines lost their parent anchor",
    ) as exc_info:
        load_same_side_bundle_import(
            job=SimpleNamespace(id="job-child-threshold-fail", agency_id=1),
            user_id=1,
            review_rows=[],
            errors=errors,
            result=result,
            artifact=artifact,
        )

    assert len(exc_info.value.row_errors) == 2
    assert result.success is False
    assert len(errors) == 2


def test_load_same_side_bundle_uses_ambiguous_parent_wording_for_negative_anchor_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _bundle_artifact(
        tmp_path=tmp_path,
        root_rows=[],
        child_rows=[_child_entry(row=1, anchor_id=-1)],
        current_batch_size=1,
    )
    result = ImportResult(success=False)
    errors: list[dict[str, Any]] = []

    monkeypatch.setattr("server.services.import_load_service.get_uow", lambda: _FakeUow(object()))
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_bundle_after_commit",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_load_service.insert_batch",
        lambda *, batch_rows, **_kwargs: [1200 + index for index, _row in enumerate(batch_rows)],
    )

    with pytest.raises(
        ImportLoadConsistencyError,
        match="significant number of planned lines lost their parent anchor",
    ) as exc_info:
        load_same_side_bundle_import(
            job=SimpleNamespace(id="job-child-ambiguous", agency_id=1),
            user_id=1,
            review_rows=[],
            errors=errors,
            result=result,
            artifact=artifact,
        )

    assert errors == [
        {
            "row": 1,
            "errors": ["Planned child row had an ambiguous parent and was not anchored."],
        }
    ]
    assert exc_info.value.row_errors == [
        {
            "row": 1,
            "errors": ["A planned child row had an ambiguous parent and was not anchored."],
            "data": {"remarks": "child-1"},
        }
    ]


def test_load_same_side_bundle_root_conflicts_still_fail_even_when_child_orphans_are_at_ten_percent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _bundle_artifact(
        tmp_path=tmp_path,
        root_rows=[
            {
                "row": 1,
                "data": {"family_name": "Alpha", "phone": "0555001001"},
                "original": {"family_name": "Alpha", "phone": "0555001001"},
                "anchor_keys": ["phone:0555001001"],
            },
            {
                "row": 2,
                "data": {"family_name": "Beta", "phone": "0555001002"},
                "original": {"family_name": "Beta", "phone": "0555001002"},
                "anchor_keys": ["phone:0555001002"],
            },
        ],
        child_rows=[_child_entry(row=index, anchor_id=index) for index in range(1, 10)]
        + [_child_entry(row=10, anchor_id=0)],
        current_batch_size=2,
    )
    result = ImportResult(success=False)
    errors: list[dict[str, Any]] = []

    def _fake_insert_batch(
        *,
        entity_type: str,
        batch_rows: list[dict[str, Any]],
        **_kwargs: object,
    ) -> list[int]:
        return [1400 + index for index, _row in enumerate(batch_rows)]

    def _fake_insert_batch_refs(
        *,
        entity_type: str,
        batch_rows: list[dict[str, Any]],
        source_ordinals: list[int] | None = None,
        **_kwargs: object,
    ) -> list[CreatedRowRef]:
        assert entity_type == "client"
        if len(batch_rows) > 1:
            raise _UniqueViolation("root conflict")
        if str(batch_rows[0].get("phone", "") or "") == "0555001001":
            ordinal = 0 if not source_ordinals else int(source_ordinals[0])
            return [CreatedRowRef(source_ordinal=ordinal, created_id=1301)]
        raise _UniqueViolation("root conflict")

    monkeypatch.setattr("server.services.import_load_service.get_uow", lambda: _FakeUow(object()))
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_bundle_after_commit",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_load_conflict_isolation.insert_batch_refs",
        _fake_insert_batch_refs,
    )
    monkeypatch.setattr("server.services.import_load_service.insert_batch", _fake_insert_batch)

    with pytest.raises(
        ImportLoadConsistencyError,
        match="planned lines changed while the import was loading",
    ) as exc_info:
        load_same_side_bundle_import(
            job=SimpleNamespace(id="job-root-conflict", agency_id=1),
            user_id=1,
            review_rows=[],
            errors=errors,
            result=result,
            artifact=artifact,
        )

    assert any(
        "planned root row no longer loads safely" in " ".join(item.get("errors", [])).lower()
        for item in exc_info.value.row_errors
    )


def test_direct_and_distributed_child_load_paths_align_for_ten_percent_orphans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_rows = [_child_entry(row=index, anchor_id=index) for index in range(1, 10)] + [
        _child_entry(row=10, anchor_id=0)
    ]
    artifact = _bundle_artifact(
        tmp_path=tmp_path,
        root_rows=[],
        child_rows=child_rows,
    )
    direct_result = ImportResult(success=False)
    direct_errors: list[dict[str, Any]] = []

    monkeypatch.setattr("server.services.import_load_service.get_uow", lambda: _FakeUow(object()))
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_bundle_after_commit",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_load_service.insert_batch",
        lambda *, batch_rows, **_kwargs: [3000 + index for index, _ in enumerate(batch_rows)],
    )

    direct_outcome = load_same_side_bundle_import(
        job=SimpleNamespace(id="job-direct-child", agency_id=1),
        user_id=1,
        review_rows=[],
        errors=direct_errors,
        result=direct_result,
        artifact=artifact,
    )
    distributed_result, distributed_errors = _run_distributed_child_load(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        child_rows=child_rows,
    )
    normalized_distributed_errors = [
        {
            "row": int(item["row"]),
            "errors": list(item["errors"]),
        }
        for item in distributed_errors
    ]

    assert direct_result.created_count == distributed_result["created_count"] == 9
    assert direct_result.skipped_count == distributed_result["skipped_count"] == 0
    assert direct_result.error_count == distributed_result["error_count"] == 1
    assert direct_errors == normalized_distributed_errors
    assert distributed_errors == [
        {
            "row": 10,
            "errors": ["Planned child row lost its parent anchor during load."],
            "data": {"remarks": "child-10"},
        }
    ]
    assert direct_outcome.committed_entities == {"demande"}
    assert distributed_result["committed_entities"] == ["demande"]
