from __future__ import annotations

import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from server.imports.models import ImportChunk, ImportChunkPhase, ImportJob  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.services.import_chunk_workflow import (  # noqa: E402
    complete_phase,
    fail_phase,
    request_workflow_cancellation,
    requeue_expired_import_phases,
    workflow_payload,
)


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
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
    finally:
        cleanup.close()


def _running_phase() -> tuple[int, int, ImportChunkPhase]:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPHL")
    job = ImportJob.objects.create(
        user=user,
        agency_id=agency_id,
        filename="lease.csv",
        file_type="csv",
        source_path="fixture://lease",
        status=ImportJob.Status.RUNNING,
        stage=ImportJob.Stage.EXECUTION,
        detected_entity="client",
        result_summary={"row_count": 1},
    )
    chunk = ImportChunk.objects.create(
        job=job,
        agency_id=agency_id,
        ordinal=1,
        chunk_role=ImportChunk.Role.SINGLE,
        entity_type="client",
        row_start=1,
        row_end=1,
        row_count=1,
    )
    phase = ImportChunkPhase.objects.create(
        chunk=chunk,
        phase=ImportChunkPhase.Phase.PLAN,
        status=ImportChunkPhase.Status.RUNNING,
        task_id="task-old",
        lease_token="lease-old",
        heartbeat_at=timezone.now(),
        lease_expires_at=timezone.now() + timedelta(minutes=5),
        started_at=timezone.now(),
    )
    return agency_id, user_id, phase


def test_complete_phase_rejects_stale_lease_token() -> None:
    agency_id, user_id, phase = _running_phase()
    try:
        assert (
            complete_phase(
                phase_id=int(phase.id),
                lease_token="lease-wrong",
                metrics_payload={"processed_count": 1},
            )
            is False
        )
        phase.refresh_from_db()
        assert phase.status == ImportChunkPhase.Status.RUNNING
        assert str(phase.lease_token or "") == "lease-old"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_fail_phase_rejects_stale_lease_token() -> None:
    agency_id, user_id, phase = _running_phase()
    try:
        assert (
            fail_phase(
                phase_id=int(phase.id),
                lease_token="lease-wrong",
                error_payload={"message": "boom"},
            )
            is False
        )
        phase.refresh_from_db()
        assert phase.status == ImportChunkPhase.Status.RUNNING
        assert str(phase.lease_token or "") == "lease-old"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_requeued_phase_cannot_be_completed_by_old_worker() -> None:
    agency_id, user_id, phase = _running_phase()
    try:
        ImportJob.objects.filter(id=phase.chunk.job_id).update(status=ImportJob.Status.RUNNING)
        ImportChunkPhase.objects.filter(id=phase.id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )

        result = requeue_expired_import_phases()

        phase.refresh_from_db()
        assert result["requeued"] == 1
        assert phase.status == ImportChunkPhase.Status.QUEUED
        assert (
            complete_phase(
                phase_id=int(phase.id),
                lease_token="lease-old",
                metrics_payload={"processed_count": 1},
            )
            is False
        )
        phase.refresh_from_db()
        assert phase.status == ImportChunkPhase.Status.QUEUED
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_request_workflow_cancellation_marks_payload_and_cancels_pending_phases() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCN")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="cancel.csv",
            file_type="csv",
            source_path="fixture://cancel",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 1},
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            row_start=1,
            row_end=1,
            row_count=1,
        )
        phase = ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.PLAN,
            status=ImportChunkPhase.Status.PENDING,
        )

        cancelled = request_workflow_cancellation(job=job)

        phase.refresh_from_db()
        assert cancelled == 1
        assert phase.status == ImportChunkPhase.Status.CANCELLED
        assert workflow_payload(job)["cancel_requested"] is True
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)
