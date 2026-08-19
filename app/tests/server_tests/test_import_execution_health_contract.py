from __future__ import annotations

import csv
import uuid
from datetime import timedelta
from pathlib import Path

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

from server.api.views_import_execute import import_cancel, import_status  # noqa: E402
from server.api.views_import_preview import import_preview  # noqa: E402
from server.imports.models import ImportJob, ImportWorkflowState  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402


def _detected_columns(columns: list[tuple[str, str, float]]) -> list[dict[str, object]]:
    return [
        {
            "index": index,
            "header": header,
            "detected_type": detected_type,
            "confidence": confidence,
            "sample_values": [],
        }
        for index, (header, detected_type, confidence) in enumerate(columns)
    ]


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


def test_import_status_reports_waiting_for_worker_and_stalled() -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPHW")
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
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=75),
            queued_at=None,
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["wait_state"] == "waiting_for_worker"
        assert response.data["stalled"] is True
        assert response.data["stalled_reason"] == "worker_not_picked_up"
        assert response.data["can_cancel"] is True
        assert response.data["can_close"] is True
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_status_reports_review_submit_dispatch_stall() -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRSD")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit.csv",
            file_type="csv",
            source_path="fixture://review-submit",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "review_submit"},
            result_summary={"row_count": 1},
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=75),
            queued_at=None,
            metadata={
                "review_submit_dispatch": {
                    "task_id": "review-submit-dispatch-1",
                    "status": "pending",
                    "requested_at": (timezone.now() - timedelta(seconds=75)).isoformat(),
                    "publish_attempt_count": 0,
                }
            },
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["wait_state"] == "review_submit_dispatch"
        assert response.data["stalled"] is True
        assert response.data["stalled_reason"] == "review_submit_dispatch_pending"
        assert response.data["can_cancel"] is True
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_status_reports_started_review_submit_worker_stall() -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRSW")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit-started.csv",
            file_type="csv",
            source_path="fixture://review-submit-started",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "review_submit"},
            result_summary={"row_count": 1},
            task_id="review-submit-dispatch-started",
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=75),
            queued_at=None,
            metadata={
                "review_submit_dispatch": {
                    "task_id": "review-submit-dispatch-started",
                    "status": "started",
                    "requested_at": (timezone.now() - timedelta(seconds=90)).isoformat(),
                    "published_at": (timezone.now() - timedelta(seconds=80)).isoformat(),
                    "started_at": (timezone.now() - timedelta(seconds=75)).isoformat(),
                    "publish_attempt_count": 1,
                }
            },
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["wait_state"] == "review_submit_dispatch"
        assert response.data["wait_reason"] == "worker_running"
        assert response.data["stalled"] is True
        assert response.data["stalled_reason"] == "review_submit_worker_stalled"
        assert response.data["can_cancel"] is True
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_status_uses_review_submit_heartbeat_for_started_dispatch() -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPRSH")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-submit-heartbeat.csv",
            file_type="csv",
            source_path="fixture://review-submit-heartbeat",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            progress=0,
            progress_detail={"phase": "review_submit"},
            result_summary={"row_count": 1},
            task_id="review-submit-dispatch-heartbeat",
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="running",
            started_at=timezone.now() - timedelta(seconds=120),
            queued_at=None,
            metadata={
                "review_submit_dispatch": {
                    "task_id": "review-submit-dispatch-heartbeat",
                    "status": "started",
                    "requested_at": (timezone.now() - timedelta(seconds=140)).isoformat(),
                    "published_at": (timezone.now() - timedelta(seconds=130)).isoformat(),
                    "started_at": (timezone.now() - timedelta(seconds=120)).isoformat(),
                    "heartbeat_at": timezone.now().isoformat(),
                    "publish_attempt_count": 1,
                }
            },
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["wait_state"] == "review_submit_dispatch"
        assert response.data["wait_reason"] == "worker_running"
        assert response.data["stalled"] is False
        assert response.data["stalled_reason"] == ""
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_cancel_immediately_cancels_queued_job() -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPCQ")
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
            result_summary={"row_count": 5},
        )
        ImportWorkflowState.objects.create(
            job=job,
            status="queued",
            queued_at=timezone.now() - timedelta(seconds=30),
        )

        request = APIRequestFactory().post(f"/api/v1/import/{job.id}/cancel/", {}, format="json")
        force_authenticate(request, user=user)

        response = import_cancel(request, str(job.id))

        job.refresh_from_db()
        assert response.status_code == 200
        assert response.data["terminal_reason"] == "cancelled"
        assert response.data["cancellation_state"] == "cancelled"
        assert job.status == ImportJob.Status.FAILED
        assert job.progress == 100
        assert (job.result_summary or {}).get("terminal_reason") == "cancelled"
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_preview_returns_recovery_union_palette_for_listing_side_manual_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPMP")
    csv_path = tmp_path / "listing_recovery.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["owner", "phone", "action", "type", "location", "budget"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "owner": "Meriem",
                "phone": "0555000001",
                "action": "SELL",
                "type": "appartement",
                "location": "Hydra",
                "budget": "9000000",
            }
        )
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://listing-recovery",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="listing",
            detected_columns=_detected_columns(
                [
                    ("owner", "name", 0.95),
                    ("phone", "phone", 0.95),
                    ("action", "action", 0.30),
                    ("type", "type", 0.30),
                    ("location", "location", 0.30),
                    ("budget", "price", 0.30),
                ]
            ),
            column_mapping={"family_name": "owner", "phone": "phone"},
            result_summary={"row_count": 1},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": "listing_side",
                    "detected_entity": "listing",
                    "confidence": 0.41,
                }
            },
        )
        monkeypatch.setattr(
            "server.api.views_import_preview.download_to_temp",
            lambda *_args, **_kwargs: csv_path,
        )

        request = APIRequestFactory().post(
            "/api/v1/import/preview/",
            {
                "session_id": str(job.id),
                "entity_type": "listing",
                "column_mapping": {"family_name": "owner", "phone": "phone"},
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == 200
        assert response.data["manual_mapping_required"] is True
        assert response.data["mapping_palette_mode"] == "recovery_union"
        assert response.data["mapping_candidate_entities"] == ["listing", "offer"]
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_preview_returns_recovery_union_palette_for_client_side_manual_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPMC")
    csv_path = tmp_path / "client_recovery.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["owner", "phone", "action", "locations", "budget_min"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "owner": "Samir",
                "phone": "0555000002",
                "action": "BUY",
                "locations": "Hydra",
                "budget_min": "1400000",
            }
        )
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://client-recovery",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(
                [
                    ("owner", "name", 0.95),
                    ("phone", "phone", 0.95),
                    ("action", "action", 0.30),
                    ("locations", "locations", 0.30),
                    ("budget_min", "budget_min", 0.30),
                ]
            ),
            column_mapping={"family_name": "owner", "phone": "phone"},
            result_summary={"row_count": 1},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
                    "confidence": 0.41,
                }
            },
        )
        monkeypatch.setattr(
            "server.api.views_import_preview.download_to_temp",
            lambda *_args, **_kwargs: csv_path,
        )

        request = APIRequestFactory().post(
            "/api/v1/import/preview/",
            {
                "session_id": str(job.id),
                "entity_type": "client",
                "column_mapping": {"family_name": "owner", "phone": "phone"},
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == 200
        assert response.data["manual_mapping_required"] is True
        assert response.data["mapping_palette_mode"] == "recovery_union"
        assert response.data["mapping_candidate_entities"] == ["client", "demande"]
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_import_preview_keeps_conflicting_workbook_palette_entity_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPMW")
    csv_path = tmp_path / "workbook_conflict.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["owner", "phone", "action"])
        writer.writeheader()
        writer.writerow(
            {
                "owner": "Conflict",
                "phone": "0555000003",
                "action": "BUY",
            }
        )
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://workbook-conflict",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(
                [
                    ("owner", "name", 0.95),
                    ("phone", "phone", 0.95),
                    ("action", "action", 0.40),
                ]
            ),
            column_mapping={"family_name": "owner", "phone": "phone"},
            result_summary={"row_count": 1},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
                    "confidence": 0.60,
                },
                "sheet_profiles": [
                    {
                        "sheet_name": "Clients",
                        "confidence": 0.8,
                        "dominant_topology_side": "client_side",
                        "dominant_bundle_mode": "single_entity",
                    },
                    {
                        "sheet_name": "Listings",
                        "confidence": 0.8,
                        "dominant_topology_side": "listing_side",
                        "dominant_bundle_mode": "same_side_bundle",
                    },
                ],
            },
        )
        monkeypatch.setattr(
            "server.api.views_import_preview.download_to_temp",
            lambda *_args, **_kwargs: csv_path,
        )

        request = APIRequestFactory().post(
            "/api/v1/import/preview/",
            {
                "session_id": str(job.id),
                "entity_type": "client",
                "column_mapping": {"family_name": "owner", "phone": "phone"},
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == 200
        assert response.data["manual_mapping_required"] is True
        assert response.data["mapping_palette_mode"] == "entity_only"
    finally:
        _cleanup_agency(agency_id=agency_id)


def test_importer_watchdog_tasks_are_scheduled() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    assert "requeue-expired-import-phases" in text
    assert "prune-importer-runtime-artifacts" in text
    assert "repair-stalled-import-jobs" in text
