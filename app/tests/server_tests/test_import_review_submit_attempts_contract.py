from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from app.tests.server_tests._integration_auth_helpers import (
    cleanup_import_test_agency as _cleanup_agency,
)
from app.tests.server_tests._integration_auth_helpers import (
    create_import_pending_review_item as _create_pending_review_item,
)
from app.tests.server_tests._integration_auth_helpers import (
    detected_import_columns as _detected_columns,
)
from app.tests.server_tests._integration_auth_helpers import (
    ensure_django,
)
from app.tests.server_tests._integration_auth_helpers import (
    make_import_test_user_and_agency as _make_user_and_agency,
)

ensure_django()

from server.api.views_import_review import import_review_submit  # noqa: E402
from server.imports.models import ImportJob  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.services.import_chunk_workflow import workflow_payload  # noqa: E402
from server.services.import_review_row_actions import ReviewResolutionState  # noqa: E402
from server.services.import_review_submit_attempts import (  # noqa: E402
    request_review_submit_attempt_cancel,
)
from server.services.import_review_submit_dispatch import (  # noqa: E402
    REVIEW_SUBMIT_DISPATCH_COMPLETED,
    REVIEW_SUBMIT_DISPATCH_CONFLICT,
    REVIEW_SUBMIT_DISPATCH_FAILED,
    REVIEW_SUBMIT_DISPATCH_STARTED,
    begin_review_submit_dispatch,
    claim_review_submit_dispatch_start,
    finish_review_submit_dispatch_fresh,
    mark_review_submit_dispatch_published_fresh,
    publish_review_submit_dispatch,
)
from server.services.import_review_submit_service import run_review_submit_task  # noqa: E402
from server.services.import_workflow_storage import save_workflow_payload  # noqa: E402


def test_review_submit_publish_success_preserves_started_dispatch_state() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRRACE1")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit-race-started.csv",
            file_type="csv",
            source_path="fixture://review-submit-race-started",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            task_id="review-submit-race-started",
        )
        begin_review_submit_dispatch(
            job=job,
            task_id="review-submit-race-started",
            actor_user_id=user_id,
            agency_id=agency_id,
            schema=None,
            correlation_id="race-started",
        )
        register_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def _enqueue_review_submit(**kwargs: object) -> object:
            claimed_job, claim_status = claim_review_submit_dispatch_start(
                session_id=str(job.id),
                agency_id=agency_id,
                task_id=str(kwargs.get("task_id", "")),
            )
            assert claimed_job is not None
            assert claim_status == "started"
            return SimpleNamespace(id=str(kwargs.get("task_id", "")))

        published = publish_review_submit_dispatch(
            job=job,
            enqueue_review_submit_task_fn=_enqueue_review_submit,
            register_task_fn=lambda *args, **kwargs: register_calls.append((args, dict(kwargs))),
        )

        job.refresh_from_db()
        dispatch = dict(workflow_payload(job).get("review_submit_dispatch", {}) or {})

        assert published is True
        assert dispatch["task_id"] == "review-submit-race-started"
        assert dispatch["status"] == REVIEW_SUBMIT_DISPATCH_STARTED
        assert register_calls
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_review_submit_publish_success_preserves_completed_dispatch_state() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRRACE2")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit-race-completed.csv",
            file_type="csv",
            source_path="fixture://review-submit-race-completed",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            task_id="review-submit-race-completed",
        )
        begin_review_submit_dispatch(
            job=job,
            task_id="review-submit-race-completed",
            actor_user_id=user_id,
            agency_id=agency_id,
            schema=None,
            correlation_id="race-completed",
        )

        def _enqueue_review_submit(**kwargs: object) -> object:
            claimed_job, claim_status = claim_review_submit_dispatch_start(
                session_id=str(job.id),
                agency_id=agency_id,
                task_id=str(kwargs.get("task_id", "")),
            )
            assert claimed_job is not None
            assert claim_status == "started"
            finish_review_submit_dispatch_fresh(
                claimed_job,
                task_id=str(kwargs.get("task_id", "")),
                status=REVIEW_SUBMIT_DISPATCH_COMPLETED,
                clear_submit_payload=False,
            )
            return SimpleNamespace(id=str(kwargs.get("task_id", "")))

        published = publish_review_submit_dispatch(
            job=job,
            enqueue_review_submit_task_fn=_enqueue_review_submit,
            register_task_fn=lambda *args, **kwargs: None,
        )

        job.refresh_from_db()
        dispatch = dict(workflow_payload(job).get("review_submit_dispatch", {}) or {})

        assert published is True
        assert dispatch["task_id"] == "review-submit-race-completed"
        assert dispatch["status"] == REVIEW_SUBMIT_DISPATCH_COMPLETED
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


@pytest.mark.parametrize(
    "winning_status",
    [
        REVIEW_SUBMIT_DISPATCH_STARTED,
        REVIEW_SUBMIT_DISPATCH_COMPLETED,
        REVIEW_SUBMIT_DISPATCH_FAILED,
    ],
)
def test_review_submit_publish_failure_preserves_started_or_terminal_dispatch_state(
    winning_status: str,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRRACE3")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=f"review-submit-race-{winning_status}.csv",
            file_type="csv",
            source_path=f"fixture://review-submit-race-{winning_status}",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            task_id=f"review-submit-race-{winning_status}",
        )
        begin_review_submit_dispatch(
            job=job,
            task_id=f"review-submit-race-{winning_status}",
            actor_user_id=user_id,
            agency_id=agency_id,
            schema=None,
            correlation_id=f"race-{winning_status}",
        )

        def _enqueue_review_submit(**kwargs: object) -> object:
            claimed_job, claim_status = claim_review_submit_dispatch_start(
                session_id=str(job.id),
                agency_id=agency_id,
                task_id=str(kwargs.get("task_id", "")),
            )
            assert claimed_job is not None
            assert claim_status == "started"
            if winning_status != REVIEW_SUBMIT_DISPATCH_STARTED:
                finish_review_submit_dispatch_fresh(
                    claimed_job,
                    task_id=str(kwargs.get("task_id", "")),
                    status=winning_status,
                    clear_submit_payload=False,
                )
            raise RuntimeError("broker failed after worker updated dispatch")

        published = publish_review_submit_dispatch(
            job=job,
            enqueue_review_submit_task_fn=_enqueue_review_submit,
            register_task_fn=lambda *args, **kwargs: None,
        )

        job.refresh_from_db()
        dispatch = dict(workflow_payload(job).get("review_submit_dispatch", {}) or {})

        assert published is False
        assert dispatch["task_id"] == f"review-submit-race-{winning_status}"
        assert dispatch["status"] == winning_status
        assert dispatch.get("last_error_code", "") != "review_submit_publish_failed"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


@pytest.mark.parametrize(
    "terminal_status",
    [
        REVIEW_SUBMIT_DISPATCH_COMPLETED,
        REVIEW_SUBMIT_DISPATCH_CONFLICT,
        REVIEW_SUBMIT_DISPATCH_FAILED,
    ],
)
def test_finish_review_submit_dispatch_fresh_preserves_publish_metadata(
    terminal_status: str,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRFTF")
    try:
        task_id = f"review-submit-terminal-{terminal_status}"
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-terminal.csv",
            file_type="csv",
            source_path="fixture://review-terminal",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            task_id=task_id,
        )
        begin_review_submit_dispatch(
            job=job,
            task_id=task_id,
            actor_user_id=user_id,
            agency_id=agency_id,
            schema="",
            correlation_id="terminal-corr",
        )
        workflow = workflow_payload(job)
        workflow["review_submit"] = {
            "corrections": {},
            "decisions": {},
            "skip_rows": [],
            "bulk_operations": [],
        }
        save_workflow_payload(job, workflow)
        stale_job = ImportJob.objects.select_related("workflow_state").get(id=job.id)
        fresh_job = ImportJob.objects.get(id=job.id)

        mark_review_submit_dispatch_published_fresh(fresh_job, task_id=task_id)
        fresh_job.refresh_from_db()
        published_dispatch = dict(
            workflow_payload(fresh_job).get("review_submit_dispatch", {}) or {}
        )

        finish_review_submit_dispatch_fresh(
            stale_job,
            task_id=task_id,
            status=terminal_status,
            clear_submit_payload=True,
        )

        job.refresh_from_db()
        finished_workflow = workflow_payload(job)
        dispatch = dict(finished_workflow.get("review_submit_dispatch", {}) or {})
        assert "review_submit" not in finished_workflow
        assert dispatch["status"] == terminal_status
        assert dispatch["published_at"] == published_dispatch["published_at"]
        assert dispatch["last_attempted_at"] == published_dispatch["last_attempted_at"]
        assert dispatch["publish_attempt_count"] == published_dispatch["publish_attempt_count"]
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


@pytest.mark.parametrize(
    ("initial_status", "attempted_status"),
    [
        (REVIEW_SUBMIT_DISPATCH_FAILED, REVIEW_SUBMIT_DISPATCH_COMPLETED),
        (REVIEW_SUBMIT_DISPATCH_COMPLETED, REVIEW_SUBMIT_DISPATCH_FAILED),
    ],
)
def test_finish_review_submit_dispatch_fresh_keeps_terminal_status_monotonic(
    monkeypatch: pytest.MonkeyPatch,
    initial_status: str,
    attempted_status: str,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRFTM")
    try:
        task_id = f"review-submit-monotonic-{initial_status}-{attempted_status}"
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-terminal-monotonic.csv",
            file_type="csv",
            source_path="fixture://review-terminal-monotonic",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            task_id=task_id,
        )
        begin_review_submit_dispatch(
            job=job,
            task_id=task_id,
            actor_user_id=user_id,
            agency_id=agency_id,
            schema="",
            correlation_id="terminal-monotonic-corr",
        )
        finish_review_submit_dispatch_fresh(
            job,
            task_id=task_id,
            status=initial_status,
            clear_submit_payload=False,
        )
        job.refresh_from_db()
        first_dispatch = dict(workflow_payload(job).get("review_submit_dispatch", {}) or {})
        warnings: list[tuple[object, ...]] = []
        monkeypatch.setattr(
            "server.services.import_review_submit_attempts.logger.warning",
            lambda *args, **_kwargs: warnings.append(args),
        )

        finish_review_submit_dispatch_fresh(
            job,
            task_id=task_id,
            status=attempted_status,
            clear_submit_payload=False,
        )

        job.refresh_from_db()
        dispatch = dict(workflow_payload(job).get("review_submit_dispatch", {}) or {})
        assert dispatch["status"] == initial_status
        assert dispatch["finished_at"] == first_dispatch["finished_at"]
        assert warnings
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_cancelled_review_submit_attempt_cannot_apply_late_worker_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRFNC")
    try:
        task_id = "review-submit-cancelled-worker"
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit-cancelled.csv",
            file_type="csv",
            source_path="fixture://review-submit-cancelled",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            task_id=task_id,
        )
        begin_review_submit_dispatch(
            job=job,
            task_id=task_id,
            actor_user_id=user_id,
            agency_id=agency_id,
            schema="",
            correlation_id="cancelled-worker",
        )
        claimed_job, claim_status = claim_review_submit_dispatch_start(
            session_id=str(job.id),
            agency_id=agency_id,
            task_id=task_id,
        )
        assert claimed_job is not None
        assert claim_status == "started"
        workflow = workflow_payload(claimed_job)
        workflow["review_submit"] = {
            "corrections": {},
            "decisions": {},
            "skip_rows": [],
            "bulk_operations": [],
        }
        save_workflow_payload(claimed_job, workflow)
        transition = request_review_submit_attempt_cancel(
            job=job,
            task_id=task_id,
            reason="test_cancel",
            clear_workflow_keys=["review_submit"],
        )
        assert transition.changed is True
        apply_calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "server.services.import_review_execution_service.apply_review_resolutions",
            lambda **kwargs: apply_calls.append(dict(kwargs)) or {"created_count": 1},
        )

        result = run_review_submit_task(
            session_id=str(job.id),
            actor_user_id=user_id,
            agency_id=agency_id,
            correlation_id="cancelled-worker",
            task_id=task_id,
        )

        job.refresh_from_db()
        dispatch = dict(workflow_payload(job).get("review_submit_dispatch", {}) or {})
        assert result["status"] == "stale_ignored"
        assert apply_calls == []
        assert dispatch["status"] == "cancelled"
        assert str(dispatch.get("cancel_reason", "") or "") == "test_cancel"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_review_submit_cancellation_after_apply_begins_cannot_preempt_terminal_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRFRA")
    cancel_thread: threading.Thread | None = None
    try:
        task_id = "review-submit-apply-terminal-fence"
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit-terminal-fence.csv",
            file_type="csv",
            source_path="fixture://review-submit-terminal-fence",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            task_id=task_id,
        )
        begin_review_submit_dispatch(
            job=job,
            task_id=task_id,
            actor_user_id=user_id,
            agency_id=agency_id,
            schema="",
            correlation_id="apply-terminal-fence",
        )
        workflow = workflow_payload(job)
        workflow["review_submit"] = {
            "corrections": {},
            "decisions": {},
            "skip_rows": [],
            "bulk_operations": [],
        }
        save_workflow_payload(job, workflow)

        monkeypatch.setattr(
            "server.services.import_review_submit_service._build_prepared_submit",
            lambda **_kwargs: (
                SimpleNamespace(
                    pending_rows=[],
                    corrections={},
                    decisions={},
                    skip_rows=[],
                ),
                [],
                {},
                {},
            ),
        )
        cancel_started = threading.Event()
        cancel_results: list[object] = []

        def _request_cancel_after_apply_started() -> None:
            cancel_started.set()
            cancel_results.append(
                request_review_submit_attempt_cancel(
                    job=ImportJob.objects.get(id=job.id),
                    task_id=task_id,
                    reason="race_after_apply",
                    clear_workflow_keys=["review_submit"],
                )
            )

        def _apply_review_resolutions(**_kwargs: object) -> dict[str, object]:
            nonlocal cancel_thread
            cancel_thread = threading.Thread(
                target=_request_cancel_after_apply_started,
                name="review-submit-cancel-race-test",
            )
            cancel_thread.start()
            assert cancel_started.wait(timeout=2.0)
            time.sleep(0.1)
            return {"created_count": 1, "updated_count": 0, "skipped_count": 0}

        def _finalize_review_submission(**kwargs: object) -> None:
            locked_job = kwargs["job"]
            locked_job.status = ImportJob.Status.COMPLETED
            locked_job.stage = ImportJob.Stage.EXECUTION
            locked_job.progress = 100
            locked_job.result_summary = {"success": True, "created_count": 1}
            locked_job.progress_detail = {"phase": "done"}
            locked_job.save(
                update_fields=[
                    "status",
                    "stage",
                    "progress",
                    "result_summary",
                    "progress_detail",
                    "updated_at",
                ]
            )

        monkeypatch.setattr(
            "server.services.import_review_execution_service.apply_review_resolutions",
            _apply_review_resolutions,
        )
        monkeypatch.setattr(
            "server.services.import_review_submit_service.finalize_review_submission",
            _finalize_review_submission,
        )

        result = run_review_submit_task(
            session_id=str(job.id),
            actor_user_id=user_id,
            agency_id=agency_id,
            correlation_id="apply-terminal-fence",
            task_id=task_id,
        )
        if cancel_thread is not None:
            cancel_thread.join(timeout=3.0)
            assert not cancel_thread.is_alive()

        job.refresh_from_db()
        dispatch = dict(workflow_payload(job).get("review_submit_dispatch", {}) or {})
        assert result["status"] == ImportJob.Status.COMPLETED
        assert job.status == ImportJob.Status.COMPLETED
        assert job.stage == ImportJob.Stage.EXECUTION
        assert dispatch["status"] == REVIEW_SUBMIT_DISPATCH_COMPLETED
        assert "review_submit" not in workflow_payload(job)
        assert len(cancel_results) == 1
        cancel_transition = cancel_results[0]
        assert cancel_transition.changed is False
        assert cancel_transition.status == REVIEW_SUBMIT_DISPATCH_COMPLETED
    finally:
        if cancel_thread is not None and cancel_thread.is_alive():
            cancel_thread.join(timeout=3.0)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_submit_logs_unexpected_background_failure_and_masks_user_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRBGF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-background-failure.csv",
            file_type="csv",
            source_path="fixture://review-background-failure",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
        )
        _create_pending_review_item(job=job)

        monkeypatch.setattr(
            "server.services.import_review_submit_service.collect_review_actions",
            lambda **_kwargs: ReviewResolutionState(),
        )
        monkeypatch.setattr(
            "server.api.views_import_review.enqueue_import_task",
            lambda _task, **kwargs: SimpleNamespace(id=str(kwargs.get("task_id", ""))),
        )
        monkeypatch.setattr(
            "server.api.views_import_review.register_task",
            lambda *args, **kwargs: None,
        )

        def _fail_after_late_publish_metadata(**_kwargs: object) -> object:
            fresh_job = ImportJob.objects.get(id=job.id)
            mark_review_submit_dispatch_published_fresh(
                fresh_job,
                task_id=str(fresh_job.task_id or ""),
            )
            raise RuntimeError("secret boom")

        monkeypatch.setattr(
            "server.services.import_review_execution_service.apply_review_resolutions",
            _fail_after_late_publish_metadata,
        )

        logged: dict[str, object] = {}

        def _capture_exception(message: str, *args: object, **kwargs: object) -> None:
            logged["message"] = message
            logged["extra"] = dict(kwargs.get("extra", {}))

        monkeypatch.setattr(
            "server.services.import_review_submit_service.logger.exception",
            _capture_exception,
        )

        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "item_decisions": {},
                "group_decisions": {},
                "bulk_operations": [],
                "skip_item_ids": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_review_submit(request, str(job.id))
        assert response.status_code == 202

        task_id = str(response.data["task_id"] or "")
        result = run_review_submit_task(
            session_id=str(job.id),
            actor_user_id=user_id,
            agency_id=agency_id,
            correlation_id="corr-bg-failure",
            task_id=task_id,
        )

        job.refresh_from_db()
        workflow = workflow_payload(job)
        dispatch = dict(workflow.get("review_submit_dispatch", {}) or {})
        submit_error = dict((job.result_summary or {}).get("review_submit_error", {}) or {})

        assert result["status"] == ImportJob.Status.READY
        assert job.status == ImportJob.Status.READY
        assert job.stage == ImportJob.Stage.REVIEW
        assert submit_error == {
            "code": "IMPORT_REVIEW_SUBMIT_FAILED",
            "detail": "We couldn’t continue with these choices just yet. Please try again.",
        }
        assert "secret boom" not in str(job.result_summary or {})
        assert logged["message"] == "Unexpected review-submit task failure"
        assert logged["extra"] == {
            "job_id": str(job.id),
            "agency_id": agency_id,
            "actor_user_id": user_id,
            "correlation_id": "corr-bg-failure",
            "task_id": task_id,
        }
        assert "review_submit" not in workflow
        assert dispatch["status"] == "failed"
        assert dispatch["published_at"]
        assert dispatch["last_attempted_at"]
        assert dispatch["publish_attempt_count"] == 1
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)
