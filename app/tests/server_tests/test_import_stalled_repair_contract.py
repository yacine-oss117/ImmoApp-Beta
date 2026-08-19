from __future__ import annotations

import importlib
import uuid
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.utils import timezone

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

tasks_import = importlib.import_module("server.api.tasks_import")
import_execute_task = importlib.import_module("server.api.tasks_import").import_execute_task
repair_stalled_import_jobs_task = importlib.import_module(
    "server.api.tasks_maintenance"
).repair_stalled_import_jobs_task
_imports_models = importlib.import_module("server.imports.models")
ImportJob = _imports_models.ImportJob
ImportWorkflowState = _imports_models.ImportWorkflowState
ensure_schema = importlib.import_module("server.pg.schema").ensure_schema
_chunk_workflow = importlib.import_module("server.services.import_chunk_workflow")
initialize_distributed_workflow = _chunk_workflow.initialize_distributed_workflow
workflow_payload = _chunk_workflow.workflow_payload


def _make_user_and_agency(prefix: str) -> tuple[int, int, object]:
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"{prefix}{uuid.uuid4().hex[:6]}", f"{prefix} Agency")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"{prefix.lower()}_{uuid.uuid4().hex[:8]}",
            password="StrongTestPass_123!",
        )
        conn.commit()
    finally:
        conn.close()
    user = get_user_model().objects.get(id=user_id)
    return agency_id, user_id, user


def _cleanup_agency(*, agency_id: int) -> None:
    ImportJob.objects.filter(agency_id=agency_id).delete()


def _scope_repair_task_jobs(monkeypatch, *job_ids: int) -> None:
    manager = ImportJob.objects
    original_filter = manager.filter

    def _scoped_filter(*args, **kwargs):
        return original_filter(*args, **kwargs).filter(id__in=list(job_ids))

    monkeypatch.setattr(manager, "filter", _scoped_filter)


def test_stalled_repair_requeues_waiting_for_worker_job_once(monkeypatch) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRR1")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="waiting.csv",
            file_type="csv",
            source_path="fixture://waiting",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "queued"},
            result_summary={"row_count": 12},
            task_id="stale-task-1",
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=75),
            metadata={},
        )
        _scope_repair_task_jobs(monkeypatch, int(job.id))
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_next_agency_import",
            lambda **_kwargs: True,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_queued_imports",
            lambda **_kwargs: 0,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.release_execution_slot",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_notifications.emit_import_notification",
            lambda **_kwargs: None,
        )

        payload = repair_stalled_import_jobs_task(None)

        job.refresh_from_db()
        workflow = workflow_payload(job)
        assert int(payload["repaired_waiting_for_worker"]) >= 1
        assert int(payload["failed_waiting_for_worker"]) == 0
        assert job.status == ImportJob.Status.QUEUED
        assert workflow["repair_attempted"] is True
        assert workflow["repair_attempt_count"] == 1
        assert workflow["repair_last_reason"] == "worker_not_picked_up"
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_stalled_repair_fails_waiting_for_worker_job_after_one_retry(monkeypatch) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRR2")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="waiting-again.csv",
            file_type="csv",
            source_path="fixture://waiting-again",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "queued"},
            result_summary={"row_count": 12},
            task_id="stale-task-2",
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=140),
            metadata={
                "repair_attempted": True,
                "repair_attempt_count": 1,
                "repair_last_reason": "worker_not_picked_up",
            },
        )
        _scope_repair_task_jobs(monkeypatch, int(job.id))
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_next_agency_import",
            lambda **_kwargs: False,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_queued_imports",
            lambda **_kwargs: 0,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.release_execution_slot",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_notifications.emit_import_notification",
            lambda **_kwargs: None,
        )

        payload = repair_stalled_import_jobs_task(None)

        job.refresh_from_db()
        workflow = workflow_payload(job)
        assert int(payload["failed_waiting_for_worker"]) >= 1
        assert job.status == ImportJob.Status.FAILED
        assert job.progress == 100
        assert "no worker picked it up" in str(job.error_message or "").lower()
        assert workflow["repair_attempt_count"] == 2
        assert workflow["repair_last_reason"] == "worker_not_picked_up"
        assert str(workflow.get("finished_at", "") or "").strip()
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_stalled_repair_attempts_queued_redispatch(monkeypatch) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRR3")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="queued.csv",
            file_type="csv",
            source_path="fixture://queued",
            status=ImportJob.Status.QUEUED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "queued"},
            result_summary={"row_count": 4},
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="queued",
            queued_at=timezone.now() - timedelta(seconds=180),
            metadata={},
        )
        _scope_repair_task_jobs(monkeypatch, int(job.id))
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_next_agency_import",
            lambda **_kwargs: True,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_queued_imports",
            lambda **_kwargs: 0,
        )

        payload = repair_stalled_import_jobs_task(None)

        job.refresh_from_db()
        workflow = workflow_payload(job)
        assert int(payload["repaired_queued"]) >= 1
        assert workflow["repair_attempted"] is True
        assert workflow["repair_attempt_count"] == 1
        assert workflow["repair_last_reason"] == "queue_not_advancing"
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_stalled_repair_republishes_review_submit_dispatch_with_same_task_id(monkeypatch) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRSDR")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit-dispatch.csv",
            file_type="csv",
            source_path="fixture://review-submit-dispatch",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "review_submit"},
            result_summary={"row_count": 1},
            task_id="review-submit-dispatch-task",
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=75),
            metadata={
                "review_submit": {
                    "corrections": {},
                    "decisions": {},
                    "skip_rows": [],
                    "bulk_operations": [],
                },
                "review_submit_dispatch": {
                    "task_id": "review-submit-dispatch-task",
                    "status": "publish_failed",
                    "actor_user_id": int(getattr(user, "id", 0) or 0),
                    "agency_id": agency_id,
                    "schema": "",
                    "correlation_id": "repair-corr",
                    "requested_at": (timezone.now() - timedelta(seconds=75)).isoformat(),
                    "last_attempted_at": (timezone.now() - timedelta(seconds=75)).isoformat(),
                    "publish_attempt_count": 1,
                    "last_error_code": "review_submit_publish_failed",
                },
            },
        )
        _scope_repair_task_jobs(monkeypatch, int(job.id))
        dispatched: list[dict[str, object]] = []
        monkeypatch.setattr(
            "server.api.tasks_core.enqueue_import_task",
            lambda _task, **kwargs: dispatched.append(dict(kwargs))
            or SimpleNamespace(id=str(kwargs.get("task_id", ""))),
        )
        monkeypatch.setattr(
            "server.api.task_registry.register_task",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_queued_imports",
            lambda **_kwargs: 0,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_next_agency_import",
            lambda **_kwargs: False,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.release_execution_slot",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_notifications.emit_import_notification",
            lambda **_kwargs: None,
        )

        payload = repair_stalled_import_jobs_task(None)

        job.refresh_from_db()
        workflow = workflow_payload(job)
        dispatch = dict(workflow.get("review_submit_dispatch", {}) or {})
        assert int(payload["repaired_review_submit_dispatch"]) >= 1
        assert int(payload["failed_review_submit_dispatch"]) == 0
        assert dispatched
        assert dispatched[0]["task_id"] == "review-submit-dispatch-task"
        assert dispatch["status"] == "published"
        assert dispatch["task_id"] == "review-submit-dispatch-task"
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_stalled_repair_cancels_started_review_submit_dispatch_after_winning_fence(
    monkeypatch,
) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRSDS")
    try:
        published_at = (timezone.now() - timedelta(seconds=85)).isoformat()
        last_attempted_at = (timezone.now() - timedelta(seconds=84)).isoformat()
        started_at = (timezone.now() - timedelta(seconds=75)).isoformat()
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit-started-dispatch.csv",
            file_type="csv",
            source_path="fixture://review-submit-started-dispatch",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "review_submit"},
            result_summary={"row_count": 1},
            task_id="review-submit-started-task",
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=90),
            metadata={
                "review_submit": {
                    "corrections": {},
                    "decisions": {},
                    "skip_rows": [],
                    "bulk_operations": [],
                },
                "review_submit_dispatch": {
                    "task_id": "review-submit-started-task",
                    "status": "started",
                    "actor_user_id": int(getattr(user, "id", 0) or 0),
                    "agency_id": agency_id,
                    "schema": "",
                    "correlation_id": "repair-started-corr",
                    "requested_at": (timezone.now() - timedelta(seconds=95)).isoformat(),
                    "published_at": published_at,
                    "last_attempted_at": last_attempted_at,
                    "started_at": started_at,
                    "publish_attempt_count": 1,
                    "last_error_code": "",
                },
            },
        )
        _scope_repair_task_jobs(monkeypatch, int(job.id))
        dispatched: list[dict[str, object]] = []
        released_slots: list[dict[str, object]] = []
        status_signals: list[dict[str, object]] = []
        monkeypatch.setattr(
            "server.api.tasks_core.enqueue_import_task",
            lambda _task, **kwargs: dispatched.append(dict(kwargs))
            or SimpleNamespace(id=str(kwargs.get("task_id", ""))),
        )
        monkeypatch.setattr(
            "server.api.task_registry.register_task",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_queued_imports",
            lambda **_kwargs: 0,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.dispatch_next_agency_import",
            lambda **_kwargs: False,
        )
        monkeypatch.setattr(
            "server.services.import_job_queue.release_execution_slot",
            lambda **kwargs: released_slots.append(dict(kwargs)),
        )
        monkeypatch.setattr(
            "server.services.import_notifications.emit_import_notification",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.immoapp_server.business_metrics_imports.record_import_status_signal",
            lambda **kwargs: status_signals.append(dict(kwargs)),
        )

        payload = repair_stalled_import_jobs_task(None)

        job.refresh_from_db()
        workflow = workflow_payload(job)
        dispatch = dict(workflow.get("review_submit_dispatch", {}) or {})
        submit_error = dict((job.result_summary or {}).get("review_submit_error", {}) or {})
        assert dispatched == []
        assert released_slots == []
        assert int(payload["failed_review_submit_dispatch"]) == 0
        assert int(payload["repaired_review_submit_dispatch"]) >= 1
        assert int(payload["repairs_attempted"]) == 1
        assert int(payload["review_submit_dispatch"]) >= 1
        assert job.status == ImportJob.Status.READY
        assert job.stage == ImportJob.Stage.REVIEW
        assert "review_submit" not in workflow
        assert workflow["repair_attempted"] is True
        assert workflow["repair_attempt_count"] == 1
        assert workflow["repair_last_reason"] == "review_submit_worker_stalled"
        assert dispatch["status"] == "cancelled"
        assert dispatch["task_id"] == "review-submit-started-task"
        assert dispatch["published_at"] == published_at
        assert dispatch["last_attempted_at"] == last_attempted_at
        assert dispatch["started_at"] == started_at
        assert dispatch["publish_attempt_count"] == 1
        assert submit_error == {
            "code": "IMPORT_REVIEW_SUBMIT_FAILED",
            "detail": "We couldn’t continue with these choices just yet. Please try again.",
        }
        assert len(status_signals) == 1
        assert status_signals[0]["event"] == "watchdog_cancel"
        assert status_signals[0]["wait_state"] == "review_submit_dispatch"
        assert status_signals[0]["stalled_reason"] == "review_submit_worker_stalled"
        assert status_signals[0]["repair_attempted"] is True
        assert status_signals[0]["cancel_requested"] is True
        assert status_signals[0]["count"] == 1
        assert float(status_signals[0]["wait_seconds"]) >= 60
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_execute_task_ignores_stale_task_id(monkeypatch) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRR4")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="stale.csv",
            file_type="csv",
            source_path="fixture://stale",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "queued"},
            result_summary={"row_count": 1},
            task_id="fresh-task-id",
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now(),
        )
        monkeypatch.setattr(
            "server.api.tasks_import_execute.load_import_service",
            lambda _user_id: SimpleNamespace(get_job=lambda _session_id: job),
        )
        monkeypatch.setattr(
            "server.api.tasks_import_execute.load_import_user",
            lambda _user_id: None,
        )
        monkeypatch.setattr(
            "server.api.tasks_import_execute.tenant_resource_governor.note_work_completed",
            lambda **_kwargs: None,
        )

        result = import_execute_task(
            SimpleNamespace(request=SimpleNamespace(id="stale-task-id")),
            session_id=str(job.id),
            user_id=int(getattr(user, "id", 0) or 0),
            agency_id=agency_id,
            entity_type="client",
            column_mapping={"family_name": "family_name"},
        )

        assert result["status"] == "stale_ignored"
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_execute_task_dispatches_prepare_when_workflow_was_preinitialized(
    monkeypatch,
) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRR5")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="preinitialized.csv",
            file_type="csv",
            source_path="fixture://preinitialized",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            column_mapping={"family_name": "family_name", "phone": "phone"},
            result_summary={"row_count": 1},
        )
        initialize_distributed_workflow(
            job=job,
            entity_type="client",
            duplicate_strategy="review",
            skip_rows=0,
            skip_review_rows=False,
            corrections=None,
        )
        dispatched: list[tuple[object, dict[str, object]]] = []

        monkeypatch.setattr(
            "server.api.tasks_import_execute.load_import_service",
            lambda _user_id: SimpleNamespace(get_job=lambda _session_id: job),
        )
        monkeypatch.setattr(
            "server.api.tasks_import_execute.load_import_user",
            lambda _user_id: None,
        )
        monkeypatch.setattr(
            "server.api.tasks_import_execute.claim_execution_or_queue",
            lambda *_args, **_kwargs: SimpleNamespace(
                status="running",
                queue_position=0,
                agency_queue_depth=0,
            ),
        )

        @contextmanager
        def _granted_lock(_schema, _agency_id):
            yield True

        monkeypatch.setattr("server.api.tasks_import_execute.import_execution_lock", _granted_lock)
        monkeypatch.setattr(
            "server.api.tasks_import_execute.clear_db_review_state",
            lambda _job: None,
        )
        monkeypatch.setattr(
            "server.api.tasks_import.emit_import_notification",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.api.tasks_import.enqueue_import_task",
            lambda task, **kwargs: dispatched.append((task, dict(kwargs)))
            or SimpleNamespace(id="prepare-dispatch-1"),
        )
        monkeypatch.setattr(
            "server.api.tasks_import_execute.tenant_resource_governor.note_work_completed",
            lambda **_kwargs: None,
        )

        result = import_execute_task(
            SimpleNamespace(request=SimpleNamespace(id="fresh-execute-task")),
            session_id=str(job.id),
            user_id=int(getattr(user, "id", 0) or 0),
            agency_id=agency_id,
            entity_type="client",
            column_mapping={"family_name": "family_name", "phone": "phone"},
            skip_rows=0,
            duplicate_strategy="review",
            skip_review_rows=False,
            corrections=None,
            execution_cost=1,
            schema=None,
            correlation_id="test-preinitialized-workflow",
        )

        job.refresh_from_db()
        assert result["status"] == "running"
        assert dispatched
        assert dispatched[0][0] is tasks_import.import_prepare_phase_task
        assert dispatched[0][1]["session_id"] == str(job.id)
        assert job.status == ImportJob.Status.RUNNING
    finally:
        _cleanup_agency(agency_id=agency_id)
