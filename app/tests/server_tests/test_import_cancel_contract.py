from __future__ import annotations

# ruff: noqa: E402, I001

import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from server.api.views_import_execute import import_cancel
from server.imports.models import (
    ImportChunk,
    ImportChunkPhase,
    ImportJob,
    ImportWorkflowState,
)
from server.pg.schema import ensure_schema
from server.services.import_chunk_workflow import workflow_payload


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


def _cleanup_agency(*, agency_id: int, user_id: int) -> None:
    ImportJob.objects.filter(agency_id=agency_id).delete()
    cleanup = admin_conn()
    try:
        cleanup.execute("DELETE FROM demande_locations WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM offer_locations WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM offers WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM listings WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
    finally:
        cleanup.close()


def test_import_cancel_contract_immediately_cancels_queued_job() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCANQ")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="queued.csv",
            file_type="csv",
            source_path="fixture://queued-cancel",
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
            queued_at=timezone.now() - timedelta(seconds=20),
        )

        request = APIRequestFactory().post(f"/api/v1/import/{job.id}/cancel/", {}, format="json")
        force_authenticate(request, user=user)

        response = import_cancel(request, str(job.id))

        job.refresh_from_db()
        assert response.status_code == 200
        assert response.data["cancellation_state"] == "cancelled"
        assert response.data["terminal_reason"] == "cancelled"
        assert response.data["status"] == "failed"
        assert job.status == ImportJob.Status.FAILED
        assert job.progress == 100
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_cancel_contract_requests_cancellation_for_active_running_job() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCANR")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="running.csv",
            file_type="csv",
            source_path="fixture://running-cancel",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            progress=35,
            progress_detail={"phase": "load"},
            result_summary={"row_count": 8, "workflow": {"cancel_requested": False}},
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=15),
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            row_start=1,
            row_end=8,
            row_count=8,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.RUNNING,
            started_at=timezone.now() - timedelta(seconds=10),
            heartbeat_at=timezone.now() - timedelta(seconds=2),
            lease_expires_at=timezone.now() + timedelta(seconds=30),
        )

        request = APIRequestFactory().post(f"/api/v1/import/{job.id}/cancel/", {}, format="json")
        force_authenticate(request, user=user)

        response = import_cancel(request, str(job.id))

        job.refresh_from_db()
        payload = workflow_payload(job)
        assert response.status_code == 200
        assert response.data["cancellation_state"] == "cancel_requested"
        assert response.data["status"] == "running"
        assert payload["cancel_requested"] is True
        assert job.status == ImportJob.Status.RUNNING
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_cancel_contract_e2e_mode_cancels_running_job_immediately(
    monkeypatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCANE2E")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="running-e2e.csv",
            file_type="csv",
            source_path="fixture://running-e2e-cancel",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            progress=35,
            progress_detail={"phase": "load"},
            result_summary={"row_count": 8, "workflow": {"cancel_requested": False}},
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=15),
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            row_start=1,
            row_end=8,
            row_count=8,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.RUNNING,
            started_at=timezone.now() - timedelta(seconds=10),
            heartbeat_at=timezone.now() - timedelta(seconds=2),
            lease_expires_at=timezone.now() + timedelta(seconds=30),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.e2e_control.e2e_test_mode_enabled",
            lambda: True,
        )
        cleared_job_ids: list[str] = []
        monkeypatch.setattr(
            "server.api.views_import_execute.e2e_control.clear_import_pause_for_job",
            lambda **kwargs: cleared_job_ids.append(str(kwargs.get("job_id") or "")),
        )

        request = APIRequestFactory().post(f"/api/v1/import/{job.id}/cancel/", {}, format="json")
        force_authenticate(request, user=user)

        response = import_cancel(request, str(job.id))

        job.refresh_from_db()
        assert response.status_code == 200
        assert response.data["cancellation_state"] == "cancelled"
        assert response.data["terminal_reason"] == "cancelled"
        assert response.data["status"] == "failed"
        assert job.status == ImportJob.Status.FAILED
        assert str((job.result_summary or {}).get("terminal_reason") or "") == "cancelled"
        assert cleared_job_ids == [str(job.id)]
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)
