from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

import server.services.import_plan_bundle_flow as import_plan_bundle_flow  # noqa: E402
import server.services.import_plan_child_flow as import_plan_child_flow  # noqa: E402
import server.services.import_plan_common as import_plan_common  # noqa: E402
import server.services.import_plan_flows as import_plan_flows  # noqa: E402
import server.services.import_plan_single_flow as import_plan_single_flow  # noqa: E402
import server.services.import_prepare_bundle_flow as import_prepare_bundle_flow  # noqa: E402
import server.services.import_prepare_child_flow as import_prepare_child_flow  # noqa: E402
import server.services.import_prepare_flows as import_prepare_flows  # noqa: E402
import server.services.import_prepare_single_flow as import_prepare_single_flow  # noqa: E402
from server.imports.models import ImportChunk, ImportChunkPhase, ImportJob  # noqa: E402
from server.services.import_control_plane import (  # noqa: E402
    advance_workflow_dispatch,
    cancel_import_immediately,
)
from server.services.import_execution_state import (  # noqa: E402
    mark_job_failed,
    persist_direct_execution_state,
)
from server.services.import_status_payload import build_import_status_payload  # noqa: E402
from server.services.import_types import ImportResult, ReviewRowBuffer  # noqa: E402


class _FakeJob:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)
        self.saved_update_fields: list[list[str]] = []

    def save(self, *, update_fields: list[str]) -> None:
        self.saved_update_fields.append(list(update_fields))


class _FakePhase:
    def __init__(
        self,
        *,
        phase_id: int,
        phase: str,
        status: str,
        chunk_role: str,
        metrics_payload: dict[str, object] | None = None,
    ) -> None:
        self.id = phase_id
        self.phase = phase
        self.status = status
        self.chunk = SimpleNamespace(chunk_role=chunk_role)
        self.metrics_payload = dict(metrics_payload or {})
        self.saved_update_fields: list[list[str]] = []

    def save(self, *, update_fields: list[str]) -> None:
        self.saved_update_fields.append(list(update_fields))


def test_build_import_status_payload_preserves_cached_queue_depth_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_snapshot = SimpleNamespace(
        visible_review_count=0,
        pending_group_count=0,
        conflict_count=0,
        issue_counts={},
    )
    session = SimpleNamespace(
        id="job-status",
        task_id="task-status",
        result_summary={"row_count": 2},
        progress_detail={"phase": "queued"},
        inference_summary={},
        preview_rows=[],
        review_rows=[],
        status=ImportJob.Status.QUEUED,
        stage=ImportJob.Stage.EXECUTION,
        progress=0,
        error_message=None,
        detected_columns=[],
        detected_entity="client",
        column_mapping={"family_name": "family_name"},
    )
    monkeypatch.setattr(
        "server.services.import_status_payload.status_poll_after_ms",
        lambda **_kwargs: 1000,
    )

    payload = build_import_status_payload(
        session=session,
        agency_id=17,
        workflow_payload_fn=lambda _session: {
            "agency_queue_depth": 7,
            "execution_profile": "green",
            "cancel_requested": False,
        },
        ensure_review_state_fn=lambda _session: review_snapshot,
        review_count_snapshot_fn=lambda _session: review_snapshot,
        resolve_import_status_fn=lambda **_kwargs: SimpleNamespace(
            public_status="queued",
            public_stage="queued",
            overflow_blocking=False,
            review_disabled=False,
            review_disabled_reason="",
            terminal_error_count=0,
        ),
        effective_import_runtime_profile_fn=lambda: SimpleNamespace(name="green"),
        budget_state_snapshot_fn=lambda **_kwargs: {
            "budgets": {"import_execute": {"17": {"tokens": 3}}}
        },
        execution_health_snapshot_fn=lambda _session: {},
        queue_position_for_job_fn=lambda _session: 1,
        canonicalize_column_mapping_fn=lambda **_kwargs: {"family_name": "family_name"},
        derive_mapping_palette_fn=lambda **_kwargs: {"mapping_palette_mode": "entity_only"},
        live_agency_queue_depth_fn=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("live queue depth should not run when cached")
        ),
    )

    assert payload["status"] == "queued"
    assert payload["agency_queue_depth"] == 7
    assert payload["queue_position"] == 1
    assert payload["poll_after_ms"] == 1000
    assert payload["tenant_budget_remaining"] == 3
    assert payload["follow_up"] == {
        "state": "completed",
        "reason_code": "",
        "recovery_owner": "",
        "entities": [],
        "steps": {
            "cache_invalidation": {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
            "success_notification": {
                "state": "skipped",
                "reason_code": "",
                "recovery_owner": "",
            },
            "rebuild_handoff": {
                "state": "skipped",
                "reason_code": "",
                "recovery_owner": "",
            },
        },
    }
    assert payload["last_result"]["follow_up"] == payload["follow_up"]


def test_build_import_status_payload_surfaces_structured_follow_up_as_first_class_field() -> None:
    review_snapshot = SimpleNamespace(
        visible_review_count=0,
        pending_group_count=0,
        conflict_count=0,
        issue_counts={},
    )
    session = SimpleNamespace(
        id="job-status-follow-up",
        task_id="task-status-follow-up",
        result_summary={
            "row_count": 2,
            "follow_up": {
                "state": "partial",
                "reason_code": "noncritical_follow_up_failed",
                "recovery_owner": "",
                "entities": ["offer"],
                "steps": {
                    "cache_invalidation": {
                        "state": "best_effort_failed",
                        "reason_code": "cache_invalidation_failed",
                        "recovery_owner": "durable_surface_generation",
                    },
                    "success_notification": {
                        "state": "skipped",
                        "reason_code": "",
                        "recovery_owner": "",
                    },
                    "rebuild_handoff": {
                        "state": "completed",
                        "reason_code": "",
                        "recovery_owner": "",
                    },
                },
            },
        },
        progress_detail={"phase": "done"},
        inference_summary={},
        preview_rows=[],
        review_rows=[],
        status=ImportJob.Status.COMPLETED,
        stage=ImportJob.Stage.EXECUTION,
        progress=100,
        error_message=None,
        detected_columns=[],
        detected_entity="offer",
        column_mapping={"price": "price"},
    )

    payload = build_import_status_payload(
        session=session,
        agency_id=17,
        workflow_payload_fn=lambda _session: {
            "agency_queue_depth": 0,
            "execution_profile": "green",
            "cancel_requested": False,
        },
        ensure_review_state_fn=lambda _session: review_snapshot,
        review_count_snapshot_fn=lambda _session: review_snapshot,
        resolve_import_status_fn=lambda **_kwargs: SimpleNamespace(
            public_status="completed",
            public_stage="done",
            overflow_blocking=False,
            review_disabled=False,
            review_disabled_reason="",
            terminal_error_count=0,
        ),
        effective_import_runtime_profile_fn=lambda: SimpleNamespace(name="green"),
        budget_state_snapshot_fn=lambda **_kwargs: {"budgets": {}},
        execution_health_snapshot_fn=lambda _session: {},
        queue_position_for_job_fn=lambda _session: 0,
        canonicalize_column_mapping_fn=lambda **_kwargs: {"price": "price"},
        derive_mapping_palette_fn=lambda **_kwargs: {"mapping_palette_mode": "entity_only"},
        live_agency_queue_depth_fn=lambda **_kwargs: 0,
    )

    assert payload["follow_up"] == {
        "state": "partial",
        "reason_code": "noncritical_follow_up_failed",
        "recovery_owner": "",
        "entities": ["offer"],
        "steps": {
            "cache_invalidation": {
                "state": "best_effort_failed",
                "reason_code": "cache_invalidation_failed",
                "recovery_owner": "durable_surface_generation",
            },
            "success_notification": {
                "state": "skipped",
                "reason_code": "",
                "recovery_owner": "",
            },
            "rebuild_handoff": {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
        },
    }
    assert payload["last_result"]["follow_up"] == payload["follow_up"]


def test_build_import_status_payload_normalizes_legacy_follow_up_without_exposing_raw_reason_text() -> (
    None
):
    review_snapshot = SimpleNamespace(
        visible_review_count=0,
        pending_group_count=0,
        conflict_count=0,
        issue_counts={},
    )
    session = SimpleNamespace(
        id="job-status-follow-up-legacy",
        task_id="task-status-follow-up-legacy",
        result_summary={
            "row_count": 1,
            "follow_up": {
                "state": "deferred",
                "reason_code": "kombu.exceptions.OperationalError: [Errno 11001]",
                "recovery_owner": "something_internal",
                "entities": ["offer"],
                "steps": {
                    "dashboard_invalidation": {
                        "state": "best_effort_failed",
                        "reason_code": "dashboard_invalidation_failed",
                        "recovery_owner": "next_dashboard_refresh",
                    },
                    "rebuild_handoff": {
                        "state": "deferred",
                        "reason_code": "kombu.exceptions.OperationalError: [Errno 11001]",
                        "recovery_owner": "something_internal",
                    },
                },
            },
        },
        progress_detail={"phase": "done"},
        inference_summary={},
        preview_rows=[],
        review_rows=[],
        status=ImportJob.Status.COMPLETED,
        stage=ImportJob.Stage.EXECUTION,
        progress=100,
        error_message=None,
        detected_columns=[],
        detected_entity="offer",
        column_mapping={"price": "price"},
    )

    payload = build_import_status_payload(
        session=session,
        agency_id=17,
        workflow_payload_fn=lambda _session: {
            "agency_queue_depth": 0,
            "execution_profile": "green",
            "cancel_requested": False,
        },
        ensure_review_state_fn=lambda _session: review_snapshot,
        review_count_snapshot_fn=lambda _session: review_snapshot,
        resolve_import_status_fn=lambda **_kwargs: SimpleNamespace(
            public_status="completed",
            public_stage="done",
            overflow_blocking=False,
            review_disabled=False,
            review_disabled_reason="",
            terminal_error_count=0,
        ),
        effective_import_runtime_profile_fn=lambda: SimpleNamespace(name="green"),
        budget_state_snapshot_fn=lambda **_kwargs: {"budgets": {}},
        execution_health_snapshot_fn=lambda _session: {},
        queue_position_for_job_fn=lambda _session: 0,
        canonicalize_column_mapping_fn=lambda **_kwargs: {"price": "price"},
        derive_mapping_palette_fn=lambda **_kwargs: {"mapping_palette_mode": "entity_only"},
        live_agency_queue_depth_fn=lambda **_kwargs: 0,
    )

    assert payload["follow_up"] == {
        "state": "deferred",
        "reason_code": "rebuild_enqueue_failed",
        "recovery_owner": "existing_match_recovery",
        "entities": ["offer"],
        "steps": {
            "cache_invalidation": {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
            "success_notification": {
                "state": "skipped",
                "reason_code": "",
                "recovery_owner": "",
            },
            "rebuild_handoff": {
                "state": "deferred",
                "reason_code": "rebuild_enqueue_failed",
                "recovery_owner": "existing_match_recovery",
            },
        },
    }
    assert "kombu.exceptions" not in str(payload["follow_up"])
    assert "dashboard_invalidation" not in str(payload["follow_up"])
    assert payload["last_result"]["follow_up"] == payload["follow_up"]


def test_cancel_import_immediately_shapes_cancelled_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.services.import_control_plane.clear_db_review_state", lambda _job: None
    )
    saved_workflows: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []
    job = _FakeJob(
        id="job-cancel",
        filename="cancel.csv",
        detected_entity="client",
        result_summary={"row_count": 4, "created_count": 1, "error_count": 0},
        progress_detail={"phase": "queued"},
        review_rows=[{"row": 1}],
        status=ImportJob.Status.QUEUED,
        stage=ImportJob.Stage.EXECUTION,
        progress=0,
        error_message=None,
    )

    cancel_import_immediately(
        job=job,
        user_id=9,
        request_workflow_cancellation_fn=lambda **_kwargs: 1,
        workflow_payload_fn=lambda _job: {"status": "queued"},
        save_workflow_payload_fn=lambda _job, payload: saved_workflows.append(dict(payload)),
        emit_import_notification_fn=lambda **kwargs: notifications.append(dict(kwargs)),
    )

    assert job.status == ImportJob.Status.FAILED
    assert job.progress == 100
    assert job.error_message == "This import was cancelled before completion."
    assert job.result_summary["terminal_reason"] == "cancelled"
    assert saved_workflows[-1]["status"] == ImportJob.Status.FAILED
    assert notifications[-1]["event_type"] == "import.execution_failed"


def test_advance_workflow_dispatch_queues_child_plan_and_root_load_after_root_plan_ready() -> None:
    saved_payloads: list[dict[str, Any]] = []
    persisted_manifests: list[dict[str, Any]] = []
    job = _FakeJob(
        id="job-dispatch",
        status=ImportJob.Status.RUNNING,
        result_summary={"row_count": 4},
        progress=0,
        progress_detail={},
        inference_summary={"final_inference": {"bundle_mode": "same_side_bundle"}},
    )
    root_chunk = SimpleNamespace(chunk_role=ImportChunk.Role.ROOT)
    child_chunk = SimpleNamespace(chunk_role=ImportChunk.Role.CHILD)
    root_plan = _FakePhase(
        phase_id=11,
        phase=ImportChunkPhase.Phase.PLAN,
        status=ImportChunkPhase.Status.COMPLETED,
        chunk_role=ImportChunk.Role.ROOT,
        metrics_payload={
            "existing_anchor_map": {"phone:0555001001": 44},
            "planned_root_anchor_keys": ["phone:0555001001"],
            "processed_count": 2,
        },
    )
    child_plan = _FakePhase(
        phase_id=12,
        phase=ImportChunkPhase.Phase.PLAN,
        status=ImportChunkPhase.Status.BLOCKED,
        chunk_role=ImportChunk.Role.CHILD,
    )
    root_load = _FakePhase(
        phase_id=13,
        phase=ImportChunkPhase.Phase.LOAD,
        status=ImportChunkPhase.Status.BLOCKED,
        chunk_role=ImportChunk.Role.ROOT,
    )
    child_load = _FakePhase(
        phase_id=14,
        phase=ImportChunkPhase.Phase.LOAD,
        status=ImportChunkPhase.Status.BLOCKED,
        chunk_role=ImportChunk.Role.CHILD,
    )
    root_plan.chunk = root_chunk
    child_plan.chunk = child_chunk
    root_load.chunk = root_chunk
    child_load.chunk = child_chunk
    payload = {
        "prepare_completed": True,
        "bundle_mode": "same_side_bundle",
        "prepare_counts": {"review_count": 0, "error_count": 0, "review_overflow_count": 0},
        "root_plan_index_ready": False,
        "root_load_anchor_map_ready": False,
        "finalize_queued": False,
    }

    dispatch = advance_workflow_dispatch(
        job=job,
        payload=payload,
        chunks=[root_chunk, child_chunk],
        phases=[root_plan, child_plan, root_load, child_load],
        save_workflow_payload_fn=lambda _job, value: saved_payloads.append(dict(value)),
        persist_root_index_manifest_fn=lambda **kwargs: persisted_manifests.append(dict(kwargs))
        or {"manifest_id": 91, "checksum": "abc", "key_count": 1},
    )

    assert dispatch.plan_phase_ids == [12]
    assert dispatch.load_phase_ids == [13]
    assert child_plan.status == ImportChunkPhase.Status.QUEUED
    assert root_load.status == ImportChunkPhase.Status.QUEUED
    assert payload["root_plan_index_ready"] is True
    assert persisted_manifests[0]["artifact_kind"] == "root_plan_index"


def test_persist_direct_execution_state_preserves_overflow_blocking_review_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_reviews: list[dict[str, object]] = []
    review_rows = ReviewRowBuffer()
    review_rows.append({"row": 1, "errors": ["needs review"]})
    review_rows.overflow_count = 2
    job = _FakeJob(
        id="job-review",
        result_summary={"row_count": 5},
        progress_detail={"phase": "executing"},
        review_rows=[],
        status=ImportJob.Status.RUNNING,
        stage=ImportJob.Stage.EXECUTION,
        progress=35,
        error_message=None,
    )
    artifact = SimpleNamespace(
        total_rows=5,
        current_batch_size=2,
        chunks_total=3,
        bundle_mode="same_side_bundle",
    )
    result = ImportResult(success=True, created_count=1)

    monkeypatch.setattr(
        "server.services.import_execution_state.persist_review_state",
        lambda **kwargs: persisted_reviews.append(dict(kwargs["progress_detail"])),
    )
    monkeypatch.setattr(
        "server.services.import_execution_state.review_count_snapshot",
        lambda _job: SimpleNamespace(visible_review_count=1, pending_group_count=1),
    )
    monkeypatch.setattr(
        "server.services.import_execution_state.resolve_import_status",
        lambda **_kwargs: SimpleNamespace(
            overflow_blocking=True,
            review_disabled=True,
            review_disabled_reason="overflow blocked",
            job_status=ImportJob.Status.FAILED,
            job_stage=ImportJob.Stage.REVIEW,
        ),
    )

    persist_direct_execution_state(
        job=job,
        user_id=7,
        artifact=artifact,
        result=result,
        review_rows=review_rows,
    )

    assert persisted_reviews
    assert job.status == ImportJob.Status.FAILED
    assert job.stage == ImportJob.Stage.REVIEW
    assert job.error_message == "overflow blocked"
    assert job.result_summary["review_state"] == "emergency_overflow"
    assert job.progress_detail["review_state"] == "emergency_overflow"
    assert job.progress_detail["review_disabled"] is True


def test_mark_job_failed_clears_review_state_and_shapes_terminal_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleared_jobs: list[object] = []
    job = _FakeJob(
        id="job-failed",
        result_summary={"row_count": 3, "created_count": 1},
        progress_detail={"phase": "executing"},
        review_rows=[{"row": 2}],
        status=ImportJob.Status.RUNNING,
        stage=ImportJob.Stage.EXECUTION,
        progress=40,
        error_message=None,
    )

    monkeypatch.setattr(
        "server.services.import_execution_state.clear_db_review_state",
        lambda current_job: cleared_jobs.append(current_job),
    )
    monkeypatch.setattr(
        "server.services.import_execution_state.resolve_import_status",
        lambda **_kwargs: SimpleNamespace(
            overflow_blocking=False,
            review_disabled=False,
            review_disabled_reason="",
            job_status=ImportJob.Status.FAILED,
            job_stage=ImportJob.Stage.EXECUTION,
        ),
    )

    mark_job_failed(job, ValueError("boom"))

    assert cleared_jobs == [job]
    assert job.review_rows == []
    assert job.status == ImportJob.Status.FAILED
    assert job.progress == 100
    assert job.result_summary["review_total_count"] == 0
    assert job.progress_detail["review_state"] == "none"
    assert job.error_message == "We couldn't finish this import yet. Please try again."


def test_prepare_and_plan_facades_reexport_mode_specific_flows() -> None:
    assert (
        import_prepare_flows.prepare_single_entity_import
        is import_prepare_single_flow.prepare_single_entity_import
    )
    assert (
        import_prepare_flows.prepare_child_only_import
        is import_prepare_child_flow.prepare_child_only_import
    )
    assert (
        import_prepare_flows.prepare_same_side_bundle_import
        is import_prepare_bundle_flow.prepare_same_side_bundle_import
    )
    assert (
        import_plan_flows.plan_single_entity_import
        is import_plan_single_flow.plan_single_entity_import
    )
    assert import_plan_flows.plan_child_only_import is import_plan_child_flow.plan_child_only_import
    assert (
        import_plan_flows.plan_same_side_bundle_import
        is import_plan_bundle_flow.plan_same_side_bundle_import
    )
    assert import_plan_flows._apply_planning_recovery is import_plan_common.apply_planning_recovery
    assert (
        import_plan_flows._blocked_duplicate_resolution_error
        is import_plan_common.blocked_duplicate_resolution_error
    )
