from __future__ import annotations

import csv
import json
import shutil
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)
from app.tests.server_tests.test_import_distributed_workflow_integration import (
    _ensure_import_tables,
    _install_in_memory_artifact_store,
)

ensure_django()

import server.api.tasks_import as tasks_import_module  # noqa: E402
import server.api.tasks_import_failures as tasks_import_failures_module  # noqa: E402
import server.api.tasks_import_phase_tasks as tasks_import_phase_tasks_module  # noqa: E402
import server.services.import_chunk_workflow as import_chunk_workflow  # noqa: E402
import server.services.import_status_api_facade as import_status_api_facade  # noqa: E402
from core.contracts.import_batch_refs import CreatedRowRef  # noqa: E402
from server.api.notifications import NotificationPersistenceError  # noqa: E402
from server.api.views_import_execute import import_execute, import_status  # noqa: E402
from server.api.views_import_upload import import_complete, import_upload  # noqa: E402
from server.imports.models import (  # noqa: E402
    ImportArtifactManifest,
    ImportChunk,
    ImportChunkPhase,
    ImportJob,
    ImportReviewGroup,
    ImportReviewItem,
)
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import use_security_context  # noqa: E402
from server.services import import_executor  # noqa: E402
from server.services.import_admission_service import admit_import_execute  # noqa: E402
from server.services.import_chunk_workflow import (  # noqa: E402
    requeue_expired_import_phases,
    stage_prepared_artifact,
    workflow_payload,
)
from server.services.import_distributed_execution import (  # noqa: E402
    load_chunk_phase,
    plan_chunk_phase,
)
from server.services.import_finalize_service import finalize_distributed_import_job  # noqa: E402
from server.services.import_follow_up import normalize_follow_up_outcome  # noqa: E402
from server.services.import_job_queue import (  # noqa: E402
    QueueClaimResult,
    claim_execution_or_queue,
    dispatch_next_agency_import,
    release_execution_slot,
)
from server.services.import_load_service import (  # noqa: E402
    ImportLoadConsistencyError,
    load_same_side_bundle_import,
)
from server.services.import_planning_service import (  # noqa: E402
    plan_child_only_import,
    plan_same_side_bundle_import,
    plan_single_entity_import,
)
from server.services.import_prepare_service import (  # noqa: E402
    prepare_same_side_bundle_import,
    prepare_single_entity_import,
)
from server.services.import_rebuild_handoff import (  # noqa: E402
    schedule_review_corrections_after_commit,
    schedule_single_entity_after_commit,
)
from server.services.import_review_runtime_state import persist_review_state  # noqa: E402
from server.services.import_review_store import (  # noqa: E402
    apply_item_resolutions,
    paged_review_groups,
)
from server.services.import_types import ImportResult, PreparedImportArtifact  # noqa: E402


def _detected_columns(headers: list[str]) -> list[dict[str, object]]:
    return [
        {
            "index": index,
            "header": header,
            "detected_type": "unknown",
            "confidence": 1.0,
            "sample_values": [],
        }
        for index, header in enumerate(headers)
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


def _cleanup_agency(*, agency_id: int, user_id: int) -> None:
    ImportJob.objects.filter(agency_id=agency_id).delete()
    cleanup = admin_conn()
    try:
        cleanup.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            "DELETE FROM storage_objects WHERE agency_id = %s OR user_id = %s",
            (agency_id, user_id),
        )
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
    finally:
        cleanup.close()


class _OnCommitCaptureSession:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def on_commit(self, callback: object) -> None:
        self.callbacks.append(callback)


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


def _expected_follow_up(
    *,
    state: str = "completed",
    entities: list[str] | None = None,
    cache_state: str = "completed",
    success_notification_state: str = "skipped",
    rebuild_state: str = "skipped",
) -> dict[str, object]:
    normalized_entities = list(entities or [])
    return {
        "state": state,
        "reason_code": (
            "rebuild_enqueue_failed"
            if state == "deferred"
            else ("noncritical_follow_up_failed" if state == "partial" else "")
        ),
        "recovery_owner": "existing_match_recovery" if state == "deferred" else "",
        "entities": normalized_entities,
        "steps": {
            "cache_invalidation": {
                "state": cache_state,
                "reason_code": (
                    "cache_invalidation_failed" if cache_state == "best_effort_failed" else ""
                ),
                "recovery_owner": (
                    "durable_surface_generation" if cache_state == "best_effort_failed" else ""
                ),
            },
            "success_notification": {
                "state": success_notification_state,
                "reason_code": (
                    "notification_record_deferred"
                    if success_notification_state == "deferred"
                    else ""
                ),
                "recovery_owner": (
                    "canonical_notification_subsystem"
                    if success_notification_state == "deferred"
                    else ""
                ),
            },
            "rebuild_handoff": {
                "state": rebuild_state,
                "reason_code": "rebuild_enqueue_failed" if rebuild_state == "deferred" else "",
                "recovery_owner": "existing_match_recovery" if rebuild_state == "deferred" else "",
            },
        },
    }


def test_normalize_follow_up_outcome_drops_legacy_dashboard_step() -> None:
    normalized = normalize_follow_up_outcome(
        {
            "state": "partial",
            "entities": ["offer"],
            "steps": {
                "cache_invalidation": {
                    "state": "best_effort_failed",
                    "reason_code": "cache_invalidation_failed",
                    "recovery_owner": "durable_surface_generation",
                },
                "dashboard_invalidation": {
                    "state": "best_effort_failed",
                    "reason_code": "dashboard_invalidation_failed",
                    "recovery_owner": "next_dashboard_refresh",
                },
                "success_notification": {
                    "state": "completed",
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
    )

    assert normalized == _expected_follow_up(
        state="partial",
        entities=["offer"],
        cache_state="best_effort_failed",
        success_notification_state="completed",
        rebuild_state="completed",
    )


def test_prepare_single_entity_dedupes_root_phone_file_wide(tmp_path: Path) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSD")
    csv_path = tmp_path / "single-root-dedup.csv"
    headers = ["family_name", "phone", "status"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Alice", "0555001001", "active"])
        writer.writerow(["Bob", "0555001002", "active"])
        writer.writerow(["Alice Duplicate", "0555 001001", "active"])

    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://single-root-dedup",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 3},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_single_entity_import(
                job=job,
                user_id=user_id,
                entity_type="client",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact.prepared_entries_path is not None
        rows = artifact.prepared_entries_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 2
        assert any(
            "Duplicate phone in this file" in " ".join(row.get("remarks", []))
            for row in review_rows
        )
        duplicate_row = next(
            row
            for row in review_rows
            if "Duplicate phone in this file" in " ".join(row.get("remarks", []))
        )
        assert duplicate_row["suggested_action"] == "review_ambiguous"
        assert result.skipped_count == 1
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        cleanup = admin_conn()
        try:
            cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
            cleanup.commit()
        finally:
            cleanup.close()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_same_side_bundle_dedupes_root_phone_file_wide(tmp_path: Path) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSB")
    csv_path = tmp_path / "bundle-root-dedup.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Bundle A", "0555002001", "active", "", "", "", "", "", "", "", "", ""])
        writer.writerow(
            [
                "Bundle A",
                "0555002001",
                "",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1200000",
                "2400000",
                "60",
                "130",
                "2",
            ]
        )
        writer.writerow(["Bundle B", "0555002002", "active", "", "", "", "", "", "", "", "", ""])
        writer.writerow(
            ["Bundle A Duplicate", "0555 002001", "active", "", "", "", "", "", "", "", "", ""]
        )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-root-dedup",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 4},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact.root_entries_path is not None
        assert artifact.child_entries_path is not None
        root_rows = artifact.root_entries_path.read_text(encoding="utf-8").strip().splitlines()
        child_rows = artifact.child_entries_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(root_rows) == 2
        assert len(child_rows) == 1
        assert any(
            "Duplicate root key in this file" in " ".join(row.get("remarks", []))
            for row in review_rows
        )
        duplicate_row = next(
            row
            for row in review_rows
            if "Duplicate root key in this file" in " ".join(row.get("remarks", []))
        )
        assert duplicate_row["suggested_action"] == "review_ambiguous"
        assert result.skipped_count == 2
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        cleanup = admin_conn()
        try:
            cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
            cleanup.commit()
        finally:
            cleanup.close()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_same_side_bundle_auto_skips_safe_repeated_root_rows(tmp_path: Path) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSR")
    csv_path = tmp_path / "bundle-root-repeat-safe.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "remarks",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            ["Bundle A", "0555002221", "active", "", "", "", "", "", "", "", "", "", "CLIENT_A"]
        )
        writer.writerow(
            [
                "Bundle A",
                "0555 002221",
                "active",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "CLIENT_A_NOTE",
            ]
        )
        writer.writerow(
            [
                "Bundle A",
                "0555002221",
                "",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1200000",
                "2400000",
                "60",
                "130",
                "2",
                "DEM_A_OK",
            ]
        )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-root-repeat-safe",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 3},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact.root_entries_path is not None
        assert artifact.child_entries_path is not None
        root_rows = artifact.root_entries_path.read_text(encoding="utf-8").strip().splitlines()
        child_rows = artifact.child_entries_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(root_rows) == 1
        assert len(child_rows) == 1
        assert review_rows == []
        assert result.skipped_count == 2
        assert result.dead_letter_summary == {
            "auto_skipped": 2,
            "human_skipped": 0,
            "blocking_discarded": 0,
        }
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        cleanup = admin_conn()
        try:
            cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
            cleanup.commit()
        finally:
            cleanup.close()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_same_side_bundle_prepare_plan_load_accepts_combined_rows(tmp_path: Path) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSPL")
    csv_path = tmp_path / "bundle-prepare-plan-load-combined.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "remarks",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            [
                "Bundle A",
                "0555008221",
                "active",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1200000",
                "2400000",
                "60",
                "130",
                "2",
                "DEM_A1",
            ]
        )
        writer.writerow(
            [
                "Bundle A",
                "0555008221",
                "active",
                "buy",
                "apartment",
                "16",
                "El Biar",
                "1400000",
                "2600000",
                "70",
                "140",
                "3",
                "DEM_A2",
            ]
        )
        writer.writerow(
            [
                "Bundle B",
                "0555008222",
                "active",
                "buy",
                "villa",
                "16",
                "Cheraga",
                "7000000",
                "9000000",
                "180",
                "260",
                "4",
                "DEM_B1",
            ]
        )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-prepare-plan-load-combined",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
                }
            },
            result_summary={"row_count": 3},
        )
        review_rows: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="skip",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )
            artifact = plan_same_side_bundle_import(
                job=job,
                user_id=user_id,
                duplicate_strategy="skip",
                skip_review_rows=False,
                review_rows=review_rows,
                errors=errors,
                result=result,
                artifact=artifact,
            )
            load_same_side_bundle_import(
                job=job,
                user_id=user_id,
                review_rows=review_rows,
                errors=errors,
                result=result,
                artifact=artifact,
            )

        assert result.success is True
        assert result.created_count == 5
        cleanup = admin_conn()
        try:
            client_row = cleanup.execute(
                "SELECT COUNT(*) AS c FROM clients WHERE agency_id = %s AND deleted_at IS NULL",
                (agency_id,),
            ).fetchone()
            demande_row = cleanup.execute(
                "SELECT COUNT(*) AS c FROM demandes WHERE agency_id = %s AND deleted_at IS NULL",
                (agency_id,),
            ).fetchone()
            cleanup.commit()
        finally:
            cleanup.close()
        assert client_row is not None and int(client_row["c"]) == 2
        assert demande_row is not None and int(demande_row["c"]) == 3
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        cleanup = admin_conn()
        try:
            cleanup.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
            cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
            cleanup.commit()
        finally:
            cleanup.close()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_execute_same_side_bundle_combined_rows_surfaces_no_hidden_executor_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSEX")
    csv_path = tmp_path / "bundle-execute-combined.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "remarks",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            [
                "Bundle A",
                "0555008321",
                "active",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1200000",
                "2400000",
                "60",
                "130",
                "2",
                "DEM_A1",
            ]
        )
        writer.writerow(
            [
                "Bundle A",
                "0555008321",
                "active",
                "buy",
                "apartment",
                "16",
                "El Biar",
                "1400000",
                "2600000",
                "70",
                "140",
                "3",
                "DEM_A2",
            ]
        )
        writer.writerow(
            [
                "Bundle B",
                "0555008322",
                "active",
                "buy",
                "villa",
                "16",
                "Cheraga",
                "7000000",
                "9000000",
                "180",
                "260",
                "4",
                "DEM_B1",
            ]
        )

    def _reraise(job: object, exc: Exception) -> None:
        raise exc

    monkeypatch.setattr(
        import_executor,
        "download_to_temp",
        lambda _source_path, suffix=None: csv_path,
    )
    monkeypatch.setattr(import_executor, "_mark_job_failed", _reraise)

    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-execute-combined",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
                }
            },
            result_summary={"row_count": 3},
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = import_executor.execute_import(job=job, user_id=user_id)

        assert result.success is True
        assert result.created_count == 5
    finally:
        cleanup = admin_conn()
        try:
            cleanup.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
            cleanup.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
            cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
            cleanup.commit()
        finally:
            cleanup.close()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_single_entity_auto_skips_safe_repeated_root_rows(tmp_path: Path) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSS")
    csv_path = tmp_path / "single-root-repeat-safe.csv"
    headers = ["family_name", "phone", "status", "remarks"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Alice", "0555003331", "active", "FIRST"])
        writer.writerow(["Alice", "0555 003331", "active", "SECOND"])

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://single-root-repeat-safe",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 2},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_single_entity_import(
                job=job,
                user_id=user_id,
                entity_type="client",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact.prepared_entries_path is not None
        rows = artifact.prepared_entries_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 1
        assert review_rows == []
        assert result.skipped_count == 1
        assert result.dead_letter_summary == {
            "auto_skipped": 1,
            "human_skipped": 0,
            "blocking_discarded": 0,
        }
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_load_same_side_bundle_fails_when_root_load_breaks_child_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPLS")
    csv_path = tmp_path / "bundle-load-anchor-loss.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "remarks",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            [
                "Load Root A",
                "0555017001",
                "active",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1000000",
                "2000000",
                "60",
                "120",
                "2",
                "DEM_A",
            ]
        )
        writer.writerow(
            [
                "Load Root B",
                "0555017002",
                "active",
                "buy",
                "villa",
                "16",
                "Cheraga",
                "3000000",
                "4000000",
                "120",
                "220",
                "4",
                "DEM_B",
            ]
        )

    class _UniqueViolation(RuntimeError):
        sqlstate = "23505"

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-load-anchor-loss",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
                }
            },
            result_summary={"row_count": 2},
        )
        review_rows: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="skip",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )
            artifact = plan_same_side_bundle_import(
                job=job,
                user_id=user_id,
                duplicate_strategy="skip",
                skip_review_rows=False,
                review_rows=review_rows,
                errors=errors,
                result=result,
                artifact=artifact,
            )

            def _fake_insert_batch(
                *,
                entity_type: str,
                batch_rows: list[dict[str, object]],
                **_kwargs,
            ):
                if entity_type == "demande":
                    return [9201 + index for index, _row in enumerate(batch_rows)]
                raise AssertionError(f"Unexpected entity type for plain insert path: {entity_type}")

            def _fake_insert_batch_refs(
                *,
                entity_type: str,
                batch_rows: list[dict[str, object]],
                source_ordinals: list[int] | None = None,
                **_kwargs: object,
            ) -> list[CreatedRowRef]:
                if entity_type != "client":
                    raise AssertionError(
                        f"Unexpected entity type for ref insert path: {entity_type}"
                    )
                if len(batch_rows) > 1:
                    raise _UniqueViolation("duplicate key value violates unique constraint")
                if str(batch_rows[0].get("phone", "") or "").strip() == "0555017001":
                    ordinal = 0 if not source_ordinals else int(source_ordinals[0])
                    return [CreatedRowRef(source_ordinal=ordinal, created_id=9101)]
                raise _UniqueViolation("duplicate key value violates unique constraint")

            monkeypatch.setattr(
                "server.services.import_load_conflict_isolation.insert_batch_refs",
                _fake_insert_batch_refs,
            )
            monkeypatch.setattr(
                "server.services.import_load_service.insert_batch",
                _fake_insert_batch,
            )

            with pytest.raises(
                ImportLoadConsistencyError,
                match="planned lines changed while the import was loading",
            ):
                load_same_side_bundle_import(
                    job=job,
                    user_id=user_id,
                    review_rows=review_rows,
                    errors=errors,
                    result=result,
                    artifact=artifact,
                )

        assert result.success is False
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_load_single_entity_progress_uses_processed_counts_not_source_row_numbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_path = tmp_path / "planned-single.jsonl"
    planned_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "row": 10,
                        "data": {"family_name": "Alpha", "phone": "0555001001"},
                        "original": {"family_name": "Alpha", "phone": "0555001001"},
                    }
                ),
                json.dumps(
                    {
                        "row": 20,
                        "data": {"family_name": "Beta", "phone": "0555001002"},
                        "original": {"family_name": "Beta", "phone": "0555001002"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    captured_progress: list[dict[str, int | str]] = []
    session = _OnCommitCaptureSession()
    monkeypatch.setattr(
        "server.services.import_load_service.get_uow",
        lambda: _FakeUow(session),
    )
    monkeypatch.setattr(
        "server.services.import_load_service.insert_batch",
        lambda **kwargs: [1000 + index for index, _ in enumerate(kwargs["batch_rows"], start=1)],
    )
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress",
        lambda **kwargs: captured_progress.append(
            {
                "rows_processed": int(kwargs.get("rows_processed", 0) or 0),
                "current_chunk": int(kwargs.get("current_chunk", 0) or 0),
                "phase": str(kwargs.get("phase", "") or ""),
            }
        ),
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_single_entity_after_commit",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr("server.api.notifications.notify_only", lambda **_kwargs: None)

    artifact = PreparedImportArtifact(
        bundle_mode="single_entity",
        total_rows=2,
        current_batch_size=10,
        chunks_total=1,
        planned_entries_path=planned_path,
    )
    result = ImportResult(success=False)

    from server.services.import_load_service import load_single_entity_import

    load_single_entity_import(
        job=SimpleNamespace(id="job-single-progress", agency_id=1),
        user_id=1,
        entity_type="client",
        review_rows=[],
        result=result,
        artifact=artifact,
    )

    executing_updates = [
        int(call["rows_processed"])
        for call in captured_progress
        if str(call["phase"]) == "executing"
    ]
    assert executing_updates[:2] == [1, 2]


def test_load_same_side_bundle_progress_tracks_root_batches_even_when_one_batch_creates_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_root_path = tmp_path / "planned-root.jsonl"
    planned_root_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "row": 1,
                        "data": {"family_name": "Alpha", "phone": "0555001001"},
                        "original": {"family_name": "Alpha", "phone": "0555001001"},
                        "anchor_keys": ["phone:0555001001"],
                    }
                ),
                json.dumps(
                    {
                        "row": 2,
                        "data": {"family_name": "Beta", "phone": "0555001002"},
                        "original": {"family_name": "Beta", "phone": "0555001002"},
                        "anchor_keys": ["phone:0555001002"],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    planned_child_path = tmp_path / "planned-child.jsonl"
    planned_child_path.write_text("", encoding="utf-8")

    captured_progress: list[dict[str, int | str]] = []
    session = _OnCommitCaptureSession()
    monkeypatch.setattr(
        "server.services.import_load_service.get_uow",
        lambda: _FakeUow(session),
    )

    def _fake_insert_batch(*, entity_type: str, batch_rows: list[dict[str, object]], **_kwargs):
        if entity_type == "demande":
            return []
        raise AssertionError(f"Unexpected entity type for plain insert path: {entity_type}")

    def _fake_insert_batch_refs(
        *,
        entity_type: str,
        batch_rows: list[dict[str, object]],
        source_ordinals: list[int] | None = None,
        **_kwargs: object,
    ) -> list[CreatedRowRef]:
        if entity_type != "client":
            raise AssertionError(f"Unexpected entity type for ref insert path: {entity_type}")
        ordinal = 0 if not source_ordinals else int(source_ordinals[0])
        phone = str(batch_rows[0].get("phone", "") or "")
        created_id = 9100 if phone == "0555001001" else 9101
        return [CreatedRowRef(source_ordinal=ordinal, created_id=created_id)]

    monkeypatch.setattr(
        "server.services.import_load_conflict_isolation.insert_batch_refs",
        _fake_insert_batch_refs,
    )
    monkeypatch.setattr("server.services.import_load_service.insert_batch", _fake_insert_batch)
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress",
        lambda **kwargs: captured_progress.append(
            {
                "rows_processed": int(kwargs.get("rows_processed", 0) or 0),
                "current_chunk": int(kwargs.get("current_chunk", 0) or 0),
                "phase": str(kwargs.get("phase", "") or ""),
            }
        ),
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_bundle_after_commit",
        lambda **_kwargs: None,
    )

    artifact = PreparedImportArtifact(
        bundle_mode="same_side_bundle",
        total_rows=2,
        current_batch_size=1,
        chunks_total=2,
        planned_root_entries_path=planned_root_path,
        planned_child_entries_path=planned_child_path,
        root_entity="client",
        child_entity="demande",
        root_row_count=2,
        child_row_count=0,
    )
    result = ImportResult(success=False)

    load_same_side_bundle_import(
        job=SimpleNamespace(id="job-bundle-progress", agency_id=1),
        user_id=1,
        review_rows=[],
        errors=[],
        result=result,
        artifact=artifact,
    )

    root_updates = [call for call in captured_progress if str(call["phase"]) == "root_load"]
    assert [int(call["rows_processed"]) for call in root_updates] == [1, 2]
    assert [int(call["current_chunk"]) for call in root_updates] == [1, 2]


def test_load_same_side_bundle_maps_root_anchors_by_source_ordinal_even_when_refs_are_reversed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_root_path = tmp_path / "planned-root-out-of-order.jsonl"
    planned_root_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "row": 1,
                        "data": {"family_name": "Alpha", "phone": "0555002101"},
                        "original": {"family_name": "Alpha", "phone": "0555002101"},
                        "anchor_keys": ["phone:0555002101"],
                    }
                ),
                json.dumps(
                    {
                        "row": 2,
                        "data": {"family_name": "Beta", "phone": "0555002102"},
                        "original": {"family_name": "Beta", "phone": "0555002102"},
                        "anchor_keys": ["phone:0555002102"],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    planned_child_path = tmp_path / "planned-child-out-of-order.jsonl"
    planned_child_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "row": 10,
                        "data": {"remarks": "child-alpha"},
                        "original": {"remarks": "child-alpha"},
                        "anchor_id": 0,
                        "anchor_key": "phone:0555002101",
                    }
                ),
                json.dumps(
                    {
                        "row": 20,
                        "data": {"remarks": "child-beta"},
                        "original": {"remarks": "child-beta"},
                        "anchor_id": 0,
                        "anchor_key": "phone:0555002102",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    captured_child_rows: list[dict[str, object]] = []
    session = _OnCommitCaptureSession()
    monkeypatch.setattr(
        "server.services.import_load_service.get_uow",
        lambda: _FakeUow(session),
    )
    monkeypatch.setattr(
        "server.services.import_load_service.persist_job_progress",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_load_service.schedule_bundle_after_commit",
        lambda **_kwargs: None,
    )

    def _fake_insert_batch_refs(
        *,
        entity_type: str,
        batch_rows: list[dict[str, object]],
        source_ordinals: list[int] | None = None,
        **_kwargs: object,
    ) -> list[CreatedRowRef]:
        assert entity_type == "client"
        assert source_ordinals == [0, 1]
        return [
            CreatedRowRef(source_ordinal=1, created_id=9201),
            CreatedRowRef(source_ordinal=0, created_id=9202),
        ]

    def _fake_insert_batch(
        *,
        entity_type: str,
        batch_rows: list[dict[str, object]],
        **_kwargs: object,
    ) -> list[int]:
        assert entity_type == "demande"
        captured_child_rows.extend(dict(row) for row in batch_rows)
        return [9301 + index for index, _row in enumerate(batch_rows)]

    monkeypatch.setattr(
        "server.services.import_load_conflict_isolation.insert_batch_refs",
        _fake_insert_batch_refs,
    )
    monkeypatch.setattr("server.services.import_load_service.insert_batch", _fake_insert_batch)

    artifact = PreparedImportArtifact(
        bundle_mode="same_side_bundle",
        total_rows=4,
        current_batch_size=10,
        chunks_total=1,
        planned_root_entries_path=planned_root_path,
        planned_child_entries_path=planned_child_path,
        root_entity="client",
        child_entity="demande",
        root_row_count=2,
        child_row_count=2,
    )
    result = ImportResult(success=False)

    load_same_side_bundle_import(
        job=SimpleNamespace(id="job-bundle-out-of-order", agency_id=1),
        user_id=1,
        review_rows=[],
        errors=[],
        result=result,
        artifact=artifact,
    )

    assert result.success is True
    assert captured_child_rows == [
        {"remarks": "child-alpha", "client_id": 9202},
        {"remarks": "child-beta", "client_id": 9201},
    ]


def test_distributed_load_chunk_phase_fails_on_lost_parent_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPLC")
    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="chunk-anchor-loss.csv",
            file_type="csv",
            source_path="fixture://chunk-anchor-loss",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
            result_summary={"row_count": 1},
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            row_start=1,
            row_end=1,
            row_count=1,
        )
        phase = ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token="lease-anchor-loss",
        )
        import_chunk_workflow.persist_jsonl_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.PLAN,
            artifact_kind="planned",
            rows=[
                {
                    "row": 1,
                    "data": {
                        "action": "buy",
                        "type": "apartment",
                        "wilaya": 16,
                        "locations": "Hydra",
                        "budget_min": 1000000,
                        "budget_max": 1800000,
                        "surface_min": 60,
                        "surface_max": 110,
                        "beds_min": 2,
                    },
                    "original": {
                        "family_name": "Anchor Lost",
                        "phone": "0555017999",
                        "remarks": "DEM_LOST",
                    },
                    "anchor_id": 0,
                    "anchor_key": "client:phone:0555017999",
                }
            ],
            chunk=chunk,
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with pytest.raises(
                ImportLoadConsistencyError,
                match="significant number of planned lines lost their parent anchor",
            ):
                load_chunk_phase(phase=phase, user_id=user_id)
        manifest = ImportArtifactManifest.objects.filter(
            job=job,
            chunk=chunk,
            phase=ImportArtifactManifest.Phase.LOAD,
            artifact_kind="load_errors",
        ).first()
        assert manifest is not None
        persisted_rows = import_chunk_workflow.load_jsonl_manifest_rows(manifest)
        assert len(persisted_rows) == 1
        assert (
            "lost its parent anchor"
            in " ".join(
                str(value) for value in list(persisted_rows[0].get("errors", []) or [])
            ).lower()
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_distributed_load_chunk_phase_requires_completed_root_load_before_child_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPLG")
    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="chunk-root-guard.csv",
            file_type="csv",
            source_path="fixture://chunk-root-guard",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
            result_summary={"row_count": 1},
        )
        ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.ROOT,
            entity_type="client",
            row_start=1,
            row_end=1,
            row_count=1,
        )
        child_chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=2,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            row_start=1,
            row_end=1,
            row_count=1,
        )
        phase = ImportChunkPhase.objects.create(
            chunk=child_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token="lease-root-guard",
        )
        import_chunk_workflow.persist_jsonl_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.PLAN,
            artifact_kind="planned",
            rows=[
                {
                    "row": 1,
                    "data": {"remarks": "CHILD_ROW"},
                    "original": {"remarks": "CHILD_ROW"},
                    "anchor_id": 77,
                    "anchor_key": "",
                }
            ],
            chunk=child_chunk,
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with pytest.raises(
                ValueError,
                match=rf"Cannot load child chunk {child_chunk.id}: root chunk load has not completed yet\.",
            ):
                load_chunk_phase(phase=phase, user_id=user_id)
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_distributed_plan_chunk_phase_uses_ambiguous_parent_review_remark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPAR")
    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="chunk-ambiguous-parent.csv",
            file_type="csv",
            source_path="fixture://chunk-ambiguous-parent",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 1},
        )
        import_chunk_workflow.save_workflow_payload(
            job,
            {
                "bundle_mode": "same_side_bundle",
                "topology_side": "client_side",
                "params": {"skip_review_rows": False},
            },
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            row_start=1,
            row_end=1,
            row_count=1,
        )
        phase = ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.PLAN,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token="lease-ambiguous-parent",
        )
        import_chunk_workflow.persist_jsonl_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.PREPARE,
            artifact_kind="prepared",
            rows=[
                {
                    "row": 1,
                    "data": {"family_name": "Ambiguous Parent", "phone": "0555001444"},
                    "original": {"family_name": "Ambiguous Parent", "phone": "0555001444"},
                }
            ],
            chunk=chunk,
        )
        monkeypatch.setattr(
            "server.services.import_distributed_execution.prefetch_root_match_cache",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_distributed_execution.prefetch_child_match_cache",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_distributed_execution.resolve_child_anchor",
            lambda **_kwargs: -1,
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = plan_chunk_phase(phase=phase, user_id=user_id)

        assert result["review_count"] == 1
        manifest = ImportArtifactManifest.objects.filter(
            job=job,
            chunk=chunk,
            phase=ImportArtifactManifest.Phase.PLAN,
            artifact_kind="review_rows",
        ).first()
        assert manifest is not None
        review_rows = import_chunk_workflow.load_jsonl_manifest_rows(manifest)
        assert review_rows and any(
            "confidence was too low to anchor automatically"
            in " ".join(str(value) for value in list(row.get("remarks", []) or [])).lower()
            for row in review_rows
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_distributed_load_chunk_phase_allows_child_orphans_at_ten_percent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPLO")
    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="chunk-child-threshold.csv",
            file_type="csv",
            source_path="fixture://chunk-child-threshold",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
            result_summary={"row_count": 10},
        )
        root_chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.ROOT,
            entity_type="client",
            row_start=1,
            row_end=1,
            row_count=1,
        )
        ImportChunkPhase.objects.create(
            chunk=root_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
        )
        child_chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=2,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            row_start=1,
            row_end=10,
            row_count=10,
        )
        phase = ImportChunkPhase.objects.create(
            chunk=child_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token="lease-child-threshold",
        )
        import_chunk_workflow.persist_jsonl_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.PLAN,
            artifact_kind="planned",
            rows=[
                {
                    "row": index,
                    "data": {"remarks": f"child-{index}"},
                    "original": {"remarks": f"child-{index}"},
                    "anchor_id": index,
                    "anchor_key": "",
                }
                for index in range(1, 10)
            ]
            + [
                {
                    "row": 10,
                    "data": {"remarks": "child-10"},
                    "original": {"remarks": "child-10"},
                    "anchor_id": 0,
                    "anchor_key": "client:phone:0555001999",
                }
            ],
            chunk=child_chunk,
        )
        monkeypatch.setattr(
            "server.services.import_distributed_execution.insert_batch",
            lambda *, batch_rows, **_kwargs: [
                1700 + index for index, _row in enumerate(batch_rows, start=1)
            ],
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = load_chunk_phase(phase=phase, user_id=user_id)

        assert result["created_count"] == 9
        assert result["skipped_count"] == 0
        assert result["error_count"] == 1
        assert result["load_error_count"] == 1
        assert (
            ImportArtifactManifest.objects.filter(
                job=job,
                chunk=child_chunk,
                phase=ImportArtifactManifest.Phase.LOAD,
                artifact_kind="load_errors",
            ).count()
            == 1
        )
        manifest = ImportArtifactManifest.objects.filter(
            job=job,
            chunk=child_chunk,
            phase=ImportArtifactManifest.Phase.LOAD,
            artifact_kind="load_errors",
        ).first()
        assert manifest is not None
        persisted_rows = import_chunk_workflow.load_jsonl_manifest_rows(manifest)
        assert persisted_rows == [
            {
                "row": 10,
                "errors": ["Planned child row lost its parent anchor during load."],
                "data": {"remarks": "child-10"},
            }
        ]
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_distributed_load_chunk_phase_uses_ambiguous_parent_wording_for_negative_anchor_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPAN")
    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="chunk-ambiguous-load.csv",
            file_type="csv",
            source_path="fixture://chunk-ambiguous-load",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
            result_summary={"row_count": 1},
        )
        root_chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.ROOT,
            entity_type="client",
            row_start=1,
            row_end=1,
            row_count=1,
        )
        ImportChunkPhase.objects.create(
            chunk=root_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
        )
        child_chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=2,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            row_start=1,
            row_end=1,
            row_count=1,
        )
        phase = ImportChunkPhase.objects.create(
            chunk=child_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token="lease-ambiguous-load",
        )
        import_chunk_workflow.persist_jsonl_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.PLAN,
            artifact_kind="planned",
            rows=[
                {
                    "row": 1,
                    "data": {"remarks": "AMBIGUOUS_PARENT"},
                    "original": {"remarks": "AMBIGUOUS_PARENT"},
                    "anchor_id": -1,
                    "anchor_key": "",
                }
            ],
            chunk=child_chunk,
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with pytest.raises(
                ImportLoadConsistencyError,
                match="significant number of planned lines lost their parent anchor",
            ):
                load_chunk_phase(phase=phase, user_id=user_id)
        manifest = ImportArtifactManifest.objects.filter(
            job=job,
            chunk=child_chunk,
            phase=ImportArtifactManifest.Phase.LOAD,
            artifact_kind="load_errors",
        ).first()
        assert manifest is not None
        persisted_rows = import_chunk_workflow.load_jsonl_manifest_rows(manifest)
        assert persisted_rows == [
            {
                "row": 1,
                "errors": ["Planned child row had an ambiguous parent and was not anchored."],
                "data": {"remarks": "AMBIGUOUS_PARENT"},
            }
        ]
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_distributed_plan_chunk_phase_uses_review_collector_for_emergency_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPPCV")
    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="chunk-plan-overflow.csv",
            file_type="csv",
            source_path="fixture://chunk-plan-overflow",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
            result_summary={
                "row_count": 2,
                "workflow": {
                    "params": {
                        "duplicate_strategy": "review",
                        "skip_review_rows": False,
                    }
                },
            },
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.ROOT,
            entity_type="client",
            row_start=1,
            row_end=2,
            row_count=2,
        )
        phase = ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.PLAN,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token="lease-plan-overflow",
        )
        import_chunk_workflow.persist_jsonl_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.PREPARE,
            artifact_kind="prepared",
            rows=[
                {"row": 1, "data": {}, "original": {}},
                {"row": 2, "data": {}, "original": {}},
            ],
            chunk=chunk,
        )
        monkeypatch.setattr(
            "server.services.import_review_runtime.import_security_limits",
            lambda: SimpleNamespace(max_review_items_emergency=1),
        )
        monkeypatch.setattr(
            "server.services.import_types.import_security_limits",
            lambda: SimpleNamespace(max_review_items_emergency=1),
        )
        monkeypatch.setattr(
            "server.services.import_distributed_execution.validate_row",
            lambda row_data, entity_type: (row_data, ["Needs review"]),
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = plan_chunk_phase(phase=phase, user_id=user_id)

        assert result["review_count"] == 1
        assert result["review_overflow_count"] == 1
        review_manifest = ImportArtifactManifest.objects.filter(
            job=job,
            chunk=chunk,
            phase=ImportArtifactManifest.Phase.PLAN,
            artifact_kind="review_rows",
        ).first()
        assert review_manifest is not None
        assert int(review_manifest.row_count or 0) == 1
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_execute_import_marks_job_failed_on_direct_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPDF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="direct-failure.csv",
            file_type="csv",
            source_path="fixture://direct-failure",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            inference_summary={
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "detected_entity": "client",
                }
            },
            result_summary={"row_count": 1},
        )

        def _raise_prepare(**_kwargs):
            raise ValueError("planned failure")

        monkeypatch.setattr(
            import_executor,
            "prepare_single_entity_import",
            _raise_prepare,
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = import_executor.execute_import(job=job, user_id=user_id)

        job.refresh_from_db()
        assert result.success is False
        assert job.status == ImportJob.Status.FAILED
        assert job.error_message == "We couldn't finish this import yet. Please try again."
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_mark_distributed_job_failed_persists_phase_errors_into_job_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPDFG")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="failed-phase.csv",
            file_type="csv",
            source_path="fixture://failed-phase",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            progress=63,
            progress_detail={
                "phase": "executing",
                "rows_processed": 8,
                "error_count": 0,
                "review_state": "normal",
                "review_pending_group_count": 2,
            },
            result_summary={
                "row_count": 10,
                "error_count": 0,
                "review_state": "normal",
                "review_pending_group_count": 2,
            },
        )
        persist_review_state(
            job=job,
            review_rows=[
                {
                    "row": 1,
                    "entity_type": "client",
                    "data": {"family_name": "Stale Retry", "phone": "0555001234"},
                    "normalized_data": {"family_name": "Stale Retry", "phone": "0555001234"},
                    "original": {"family_name": "Stale Retry", "phone": "0555001234"},
                    "raw_data": {"family_name": "Stale Retry", "phone": "0555001234"},
                    "issue_group": "possible_duplicate",
                    "issue_title": "Possible duplicate",
                    "issue_summary": "This line needs review.",
                    "suggested_action": "review_ambiguous",
                }
            ],
            progress_detail={"phase": "review", "rows_total": 10},
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            row_start=1,
            row_end=2,
            row_count=2,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.FAILED,
            error_payload={
                "message": "A few planned lines changed while the import was loading. Restart the import so those rows can be planned again.",
                "row_errors": [
                    {
                        "row": 2,
                        "errors": ["A planned child row lost its parent anchor during load."],
                    }
                ],
            },
        )
        monkeypatch.setattr(
            tasks_import_failures_module,
            "release_execution_slot",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            tasks_import_failures_module,
            "dispatch_next_agency_import",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            tasks_import_failures_module,
            "dispatch_queued_imports",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            tasks_import_failures_module,
            "emit_import_notification",
            lambda **_kwargs: None,
        )

        tasks_import_failures_module.mark_distributed_job_failed(
            job=job,
            user_id=user_id,
            message="A few planned lines changed while the import was loading. Restart the import so those rows can be planned again.",
            schema=None,
        )

        job.refresh_from_db()
        assert job.status == ImportJob.Status.FAILED
        assert int((job.result_summary or {}).get("error_count", 0) or 0) >= 1
        assert int((job.progress_detail or {}).get("error_count", 0) or 0) >= 1
        assert any(
            "lost its parent anchor" in " ".join(item.get("errors", [])).lower()
            for item in list((job.result_summary or {}).get("errors", []) or [])
            if isinstance(item, dict)
        )
        assert int(job.progress or 0) == 63
        assert ImportReviewGroup.objects.filter(job=job).count() == 0
        assert ImportReviewItem.objects.filter(job=job).count() == 0
        assert list(job.review_rows or []) == []
        assert str((job.result_summary or {}).get("review_state", "") or "") == "none"
        assert int((job.result_summary or {}).get("review_total_count", 0) or 0) == 0
        assert str((job.progress_detail or {}).get("review_state", "") or "") == "none"
        assert int((job.progress_detail or {}).get("review_pending_group_count", 0) or 0) == 0
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_same_side_bundle_emits_root_and_child_for_combined_rows(tmp_path: Path) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSC")
    csv_path = tmp_path / "bundle-combined-rows.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "remarks",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            [
                "Bundle A",
                "0555002721",
                "active",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1200000",
                "2400000",
                "60",
                "130",
                "2",
                "DEM_A1",
            ]
        )
        writer.writerow(
            [
                "Bundle A",
                "0555 002721",
                "active",
                "buy",
                "apartment",
                "16",
                "El Biar",
                "1400000",
                "2600000",
                "70",
                "140",
                "3",
                "DEM_A2",
            ]
        )
        writer.writerow(
            [
                "Bundle B",
                "0555002722",
                "active",
                "buy",
                "villa",
                "16",
                "Cheraga",
                "7000000",
                "9000000",
                "180",
                "260",
                "4",
                "DEM_B1",
            ]
        )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-combined-rows",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 3},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact.root_entries_path is not None
        assert artifact.child_entries_path is not None
        root_rows = artifact.root_entries_path.read_text(encoding="utf-8").strip().splitlines()
        child_rows = artifact.child_entries_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(root_rows) == 2
        assert len(child_rows) == 3
        assert review_rows == []
        assert result.skipped_count == 1
        assert result.dead_letter_summary == {
            "auto_skipped": 1,
            "human_skipped": 0,
            "blocking_discarded": 0,
        }
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        cleanup = admin_conn()
        try:
            cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
            cleanup.commit()
        finally:
            cleanup.close()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_same_side_bundle_keeps_root_importable_when_child_fields_need_review(
    tmp_path: Path,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSR")
    csv_path = tmp_path / "bundle-root-safe-child-review.csv"
    headers = [
        "family_name",
        "phone",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_max",
        "surface_min",
        "beds_min",
        "remarks",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            [
                "Client Root",
                "0555007788",
                "buy",
                "carcasse",
                "16",
                "Hydra",
                "1 milliard 500",
                "environ 90",
                "3/4",
                "Needs a broad search",
            ]
        )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-root-safe-child-review",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 1},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact.root_entries_path is not None
        root_rows = artifact.root_entries_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(root_rows) == 1
        assert len(review_rows) == 1
        assert str(review_rows[0].get("entity_type", "") or "") == "demande"
        review_text = " ".join(str(item) for item in review_rows[0].get("remarks", []) or [])
        assert "carcasse" in review_text.lower()
        assert "3/4" in review_text
        assert result.skipped_count == 1
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        cleanup = admin_conn()
        try:
            cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
            cleanup.commit()
        finally:
            cleanup.close()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_same_side_bundle_conflicting_duplicate_root_blocks_when_review_skipped(
    tmp_path: Path,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSX")
    csv_path = tmp_path / "bundle-root-conflict-skip-review.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Bundle A", "0555004441", "active", "", "", "", "", "", "", "", "", ""])
        writer.writerow(["Bundle B", "0555 004441", "active", "", "", "", "", "", "", "", "", ""])
        writer.writerow(
            [
                "Bundle A",
                "0555004441",
                "",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1200000",
                "2400000",
                "60",
                "130",
                "2",
            ]
        )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-root-conflict-skip-review",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 3},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=True,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact.root_entries_path is not None
        root_rows = artifact.root_entries_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(root_rows) == 1
        assert review_rows == []
        assert result.error_count == 1
        assert any("Conflicting root fields" in " ".join(item["errors"]) for item in result.errors)
        assert result.dead_letter_summary == {
            "auto_skipped": 1,
            "human_skipped": 0,
            "blocking_discarded": 1,
        }
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_same_side_bundle_unclassified_row_stays_in_review_without_dead_letter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSU")
    csv_path = tmp_path / "bundle-unclassified-review.csv"
    headers = ["family_name", "phone", "status"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Bundle A", "0555004541", "active"])

    monkeypatch.setattr(
        "server.services.import_prepare_service.infer_row_entity",
        lambda *_args, **_kwargs: SimpleNamespace(
            entity_type="offer",
            confidence=0.15,
            reasons=["Row shape does not match the selected client/request bundle."],
        ),
    )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-unclassified-review",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 1},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact is not None
        assert len(review_rows) == 1
        assert result.skipped_count == 1
        assert result.error_count == 0
        assert result.dead_letter_summary == {
            "auto_skipped": 0,
            "human_skipped": 0,
            "blocking_discarded": 0,
        }
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_same_side_bundle_keeps_none_inference_in_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSN")
    csv_path = tmp_path / "bundle-none-inference-review.csv"
    headers = ["family_name", "phone", "status"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Bundle B", "0555004542", "active"])

    monkeypatch.setattr(
        "server.services.import_prepare_service.infer_row_entity",
        lambda *_args, **_kwargs: SimpleNamespace(
            entity_type=None,
            confidence=0.0,
            reasons=["Row carries listing-side signals inside a client-side bundle."],
        ),
    )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-none-inference-review",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 1},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact is not None
        assert len(review_rows) == 1
        assert result.skipped_count == 1
        assert result.error_count == 0
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_plan_child_only_blocks_db_duplicates_when_review_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCH")
    spool_dir = tmp_path / "child-plan-artifact"
    spool_dir.mkdir()
    prepared_entries_path = spool_dir / "prepared_child_entries.jsonl"
    prepared_entry = {
        "row": 1,
        "data": {
            "family_name": "Anchor Client",
            "phone": "0555007772",
            "action": "buy",
            "type": "apartment",
            "wilaya": "16",
            "locations": ["Hydra"],
            "budget_min": 1200000,
            "budget_max": 2400000,
        },
        "original": {
            "family_name": "Anchor Client",
            "phone": "0555007772",
            "action": "buy",
            "type": "apartment",
            "wilaya": "16",
            "locations": "Hydra",
            "budget_min": "1200000",
            "budget_max": "2400000",
        },
    }
    prepared_entries_path.write_text(json.dumps(prepared_entry) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "server.services.import_planning_service.prefetch_root_match_cache",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_planning_service.prefetch_child_match_cache",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_planning_service.resolve_child_anchor",
        lambda **_kwargs: 41,
    )
    monkeypatch.setattr(
        "server.services.import_planning_service._apply_planning_recovery",
        lambda **kwargs: dict(kwargs["row_data"]),
    )
    monkeypatch.setattr(
        "server.services.import_planning_service.validate_row",
        lambda row_data, _entity_type: (dict(row_data), []),
    )
    monkeypatch.setattr(
        "server.services.import_planning_service.resolve_existing_matches",
        lambda **_kwargs: SimpleNamespace(
            candidate_matches=[{"id": 91, "row_version": 2}],
            suggested_reasons=[
                "This line matches existing records in your agency and needs review."
            ],
        ),
    )

    artifact = PreparedImportArtifact(
        bundle_mode="single_entity",
        total_rows=1,
        current_batch_size=50,
        chunks_total=1,
        spool_dir=spool_dir,
        prepared_entries_path=prepared_entries_path,
        entity_type="demande",
        topology_side="client_side",
    )

    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="prepared-child-artifact.jsonl",
            file_type="csv",
            source_path="fixture://prepared-child-artifact",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="demande",
            detected_columns=[],
            column_mapping={},
            result_summary={"row_count": 1},
        )
        review_rows: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            planned_artifact = plan_child_only_import(
                job=job,
                user_id=user_id,
                entity_type="demande",
                duplicate_strategy="review",
                skip_review_rows=True,
                review_rows=review_rows,
                errors=errors,
                result=result,
                artifact=artifact,
            )

        assert planned_artifact.planned_entries_path is not None
        assert planned_artifact.planned_entries_path.read_text(encoding="utf-8").strip() == ""
        assert review_rows == []
        assert result.error_count == 1
        assert result.skipped_count == 0
        assert errors == [
            {
                "row": 1,
                "errors": ["This line matches existing records in your agency and needs review."],
            }
        ]
    finally:
        shutil.rmtree(spool_dir, ignore_errors=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_plan_single_entity_blocks_db_duplicates_when_review_is_skipped(tmp_path: Path) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSP")
    csv_path = tmp_path / "single-db-duplicate-skip-review.csv"
    headers = ["family_name", "phone", "status"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Alice Incoming", "0555007771", "active"])

    artifact = None
    try:
        seed = admin_conn()
        try:
            seed.execute(
                """
                INSERT INTO clients (agency_id, family_name, phone, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                """,
                (agency_id, "Alice Existing", "0555007771", "active"),
            )
            seed.commit()
        finally:
            seed.close()

        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://single-db-duplicate-skip-review",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 1},
        )
        review_rows: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_single_entity_import(
                job=job,
                user_id=user_id,
                entity_type="client",
                skip_rows=0,
                skip_review_rows=True,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )
            artifact = plan_single_entity_import(
                job=job,
                entity_type="client",
                duplicate_strategy="review",
                skip_review_rows=True,
                review_rows=review_rows,
                errors=errors,
                result=result,
                artifact=artifact,
            )

        assert artifact.planned_entries_path is not None
        assert artifact.planned_entries_path.read_text(encoding="utf-8").strip() == ""
        assert review_rows == []
        assert result.error_count == 1
        assert result.skipped_count == 0
        assert errors == [
            {
                "row": 1,
                "errors": ["This line matches existing records in your agency and needs review."],
            }
        ]
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        cleanup = admin_conn()
        try:
            cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
            cleanup.commit()
        finally:
            cleanup.close()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_claim_execution_or_queue_allows_one_running_one_queued_then_full() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPQQ")
    try:
        jobs = [
            ImportJob.objects.create(
                user=user,
                agency_id=agency_id,
                filename=f"queue-{index}.csv",
                file_type="csv",
                source_path=f"fixture://queue-{index}",
                status=ImportJob.Status.READY,
                stage=ImportJob.Stage.MAPPING,
                detected_entity="client",
                result_summary={"workflow": {"params": {"entity_type": "client"}}},
            )
            for index in range(3)
        ]
        with use_security_context(agency_id=agency_id, is_superuser=False):
            claim1 = claim_execution_or_queue(jobs[0], execution_profile="green")
            claim2 = claim_execution_or_queue(jobs[1], execution_profile="yellow")
            claim3 = claim_execution_or_queue(jobs[2], execution_profile="red")

        jobs[0].refresh_from_db()
        jobs[1].refresh_from_db()
        jobs[2].refresh_from_db()

        assert claim1.status == "running"
        assert claim2.status == "queued"
        assert claim2.queue_position == 1
        assert claim3.status == "full"
        assert jobs[0].status == ImportJob.Status.RUNNING
        assert jobs[1].status == ImportJob.Status.QUEUED
        assert jobs[2].status == ImportJob.Status.READY
    finally:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            release_execution_slot(agency_id=agency_id, owner=f"import-job:{jobs[0].id}")
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_dispatch_next_agency_import_promotes_oldest_queued_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPDQ")
    try:
        job_running = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="running.csv",
            file_type="csv",
            source_path="fixture://running",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            result_summary={
                "workflow": {"params": {"entity_type": "client", "column_mapping": {}}}
            },
        )
        job_queued = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="queued.csv",
            file_type="csv",
            source_path="fixture://queued",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            result_summary={
                "workflow": {"params": {"entity_type": "client", "column_mapping": {}}}
            },
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            assert (
                claim_execution_or_queue(job_running, execution_profile="green").status == "running"
            )
            assert (
                claim_execution_or_queue(job_queued, execution_profile="green").status == "queued"
            )

        monkeypatch.setattr(
            "server.services.import_job_queue.enqueue_import_task",
            lambda _task, **_kwargs: SimpleNamespace(id="queued-task-1"),
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            release_execution_slot(agency_id=agency_id, owner=f"import-job:{job_running.id}")
            assert dispatch_next_agency_import(agency_id=agency_id, schema=None) is True

        job_queued.refresh_from_db()
        assert job_queued.status == ImportJob.Status.RUNNING
        assert job_queued.task_id == "queued-task-1"
    finally:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            release_execution_slot(agency_id=agency_id, owner=f"import-job:{job_queued.id}")
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_admit_import_execute_degraded_fallback_is_not_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_a, user_a_id, user_a = _make_user_and_agency("IMPAA")
    agency_b, user_b_id, user_b = _make_user_and_agency("IMPAB")
    try:
        ImportJob.objects.create(
            user=user_a,
            agency_id=agency_a,
            filename="running-a.csv",
            file_type="csv",
            source_path="fixture://running-a",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
        )
        ImportJob.objects.create(
            user=user_b,
            agency_id=agency_b,
            filename="running-b.csv",
            file_type="csv",
            source_path="fixture://running-b",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
        )
        monkeypatch.setattr(
            "server.services.tenant_resource_governor.governor_backend_available",
            lambda: False,
        )

        blocked = admit_import_execute(agency_id=999999, cost=3, execution_profile="green")
        allowed = admit_import_execute(agency_id=agency_a, cost=3, execution_profile="green")

        assert blocked.degraded is True
        assert blocked.allowed is False
        assert blocked.queue_on_pressure is True
        assert blocked.execution_profile == "red"

        assert allowed.degraded is True
        assert allowed.allowed is False
        assert allowed.queue_on_pressure is True
    finally:
        _cleanup_agency(agency_id=agency_a, user_id=user_a_id)
        _cleanup_agency(agency_id=agency_b, user_id=user_b_id)


def test_requeue_expired_import_phases_requeues_running_and_cancels_failed() -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPRQ")
    try:
        running_job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="running.csv",
            file_type="csv",
            source_path="fixture://running",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            result_summary={"workflow": {"cancel_requested": False}},
        )
        failed_job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="failed.csv",
            file_type="csv",
            source_path="fixture://failed",
            status=ImportJob.Status.FAILED,
            stage=ImportJob.Stage.EXECUTION,
            result_summary={"workflow": {"cancel_requested": True}},
        )
        running_chunk = ImportChunk.objects.create(
            job=running_job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            row_start=1,
            row_end=25,
            row_count=25,
        )
        failed_chunk = ImportChunk.objects.create(
            job=failed_job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            row_start=1,
            row_end=25,
            row_count=25,
        )
        expired_at = timezone.now() - timedelta(minutes=5)
        running_phase = ImportChunkPhase.objects.create(
            chunk=running_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token="lease-running",
            lease_expires_at=expired_at,
        )
        failed_phase = ImportChunkPhase.objects.create(
            chunk=failed_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.RUNNING,
            lease_token="lease-failed",
            lease_expires_at=expired_at,
        )

        result = requeue_expired_import_phases()

        running_phase.refresh_from_db()
        failed_phase.refresh_from_db()
        assert result == {"requeued": 1, "cancelled": 1}
        assert running_phase.status == ImportChunkPhase.Status.QUEUED
        assert bool(dict(running_phase.metrics_payload).get("requeued_after_lease_expiry", False))
        assert failed_phase.status == ImportChunkPhase.Status.CANCELLED
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_stage_prepared_artifact_cleans_up_after_partial_manifest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPSC")
    csv_path = tmp_path / "stage-cleanup.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Alice", "0555003001", "active", "", "", "", "", "", "", "", "", ""])
        writer.writerow(
            [
                "Alice",
                "0555003001",
                "",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1200000",
                "2400000",
                "60",
                "130",
                "2",
            ]
        )

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://stage-cleanup",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 2},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_same_side_bundle_import(
                job=job,
                root_entity="client",
                child_entity="demande",
                topology_side="client_side",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="skip",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        call_count = {"value": 0}

        def _persist_file_manifest(**kwargs):
            call_count["value"] += 1
            if call_count["value"] >= 2:
                raise RuntimeError("manifest upload failed")
            return ImportArtifactManifest.objects.create(
                job=kwargs["job"],
                agency_id=int(kwargs["job"].agency_id),
                chunk=kwargs.get("chunk"),
                phase=str(kwargs["phase"]),
                artifact_kind=str(kwargs["artifact_kind"]),
                storage_id="",
                checksum="",
                row_count=int(kwargs.get("row_count", 0) or 0),
                metadata=dict(kwargs.get("metadata") or {}),
            )

        monkeypatch.setattr(
            "server.services.import_chunk_workflow.persist_file_manifest",
            _persist_file_manifest,
        )

        with pytest.raises(RuntimeError, match="manifest upload failed"):
            stage_prepared_artifact(
                job=job,
                artifact=artifact,
                review_rows=[],
                errors=[],
                result=result,
            )

        assert ImportChunk.objects.filter(job=job).count() == 0
        assert ImportArtifactManifest.objects.filter(job=job).count() == 0
        assert workflow_payload(job) == {}
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_distributed_import_job_batches_offer_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPFN")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="offers.csv",
            file_type="csv",
            source_path="fixture://offers",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="offer",
            result_summary={
                "row_count": 3,
                "workflow": {
                    "params": {"entity_type": "offer"},
                    "started_at": timezone.now().isoformat(),
                },
            },
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="offer",
            row_start=1,
            row_end=3,
            row_count=3,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
            metrics_payload={
                "created_count": 3,
                "skipped_count": 0,
                "error_count": 0,
                "offer_ids": [11, 12, 13],
                "committed_entities": ["offer"],
            },
        )
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "server.services.match_jobs.enqueue_rebuild_offer_pairs_batch",
            lambda offer_ids, *, agency_id: captured.update(
                {"offer_ids": list(offer_ids), "agency_id": int(agency_id)}
            ),
        )
        monkeypatch.setattr(
            "server.services.import_finalize_service.record_import_success_notification",
            lambda **kwargs: captured.update({"success_notification": dict(kwargs)})
            or {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
        )
        monkeypatch.setattr(
            "server.services.import_execution_metrics.record_import_metrics",
            lambda **_kwargs: None,
        )

        result = finalize_distributed_import_job(job=job, user_id=user_id)

        assert result["created_count"] == 3
        assert result["follow_up"] == _expected_follow_up(
            state="completed",
            entities=["offer"],
            success_notification_state="completed",
            rebuild_state="completed",
        )
        assert captured["offer_ids"] == [11, 12, 13]
        assert captured["agency_id"] == agency_id
        assert cast(dict[str, object], captured["success_notification"])["job_id"] == str(job.id)
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_schedule_single_entity_after_commit_persists_follow_up_after_rebuild_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSIC")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="single-follow-up.csv",
            file_type="csv",
            source_path="fixture://single-follow-up",
            status=ImportJob.Status.COMPLETED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 2},
        )
        session = _OnCommitCaptureSession()
        captured: dict[str, object] = {}

        monkeypatch.setattr(
            "server.services.import_rebuild_handoff.enqueue_post_import_rebuilds",
            lambda **_kwargs: captured.update({"rebuild_enqueued": True}),
        )

        schedule_single_entity_after_commit(
            write_session=session,
            entity_type="client",
            job_id=str(job.id),
            agency_id=agency_id,
            load_outcome=SimpleNamespace(
                listing_wilaya_ids=set(),
                demande_ids=set(),
                demande_client_ids=set(),
                offer_ids=set(),
            ),
        )

        assert len(session.callbacks) == 1
        callback = cast(Callable[[], None], session.callbacks[0])
        assert callable(callback)
        callback()

        assert captured["rebuild_enqueued"] is True
        job.refresh_from_db()
        assert (job.result_summary or {}).get("follow_up") == _expected_follow_up(
            state="completed",
            entities=["client"],
            success_notification_state="skipped",
            rebuild_state="completed",
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_schedule_review_corrections_after_commit_persists_follow_up_after_rebuild_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRIC")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-follow-up.csv",
            file_type="csv",
            source_path="fixture://review-follow-up",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="offer",
            result_summary={"row_count": 1},
        )
        session = _OnCommitCaptureSession()
        captured: dict[str, object] = {}

        monkeypatch.setattr(
            "server.services.import_rebuild_handoff.enqueue_post_import_rebuilds",
            lambda **_kwargs: captured.update({"rebuild_enqueued": True}),
        )

        schedule_review_corrections_after_commit(
            write_session=session,
            entity_type="offer",
            job_id=str(job.id),
            agency_id=agency_id,
            load_outcome=SimpleNamespace(
                listing_wilaya_ids=set(),
                demande_ids=set(),
                demande_client_ids=set(),
                offer_ids=set(),
            ),
        )

        assert len(session.callbacks) == 1
        callback = cast(Callable[[], None], session.callbacks[0])
        assert callable(callback)
        callback()

        assert captured["rebuild_enqueued"] is True
        job.refresh_from_db()
        assert job.status == ImportJob.Status.READY
        assert job.stage == ImportJob.Stage.REVIEW
        assert (job.result_summary or {}).get("follow_up") == _expected_follow_up(
            state="completed",
            entities=["offer"],
            success_notification_state="skipped",
            rebuild_state="completed",
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_schedule_review_corrections_after_commit_defers_follow_up_when_rebuild_handoff_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRDF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-deferred.csv",
            file_type="csv",
            source_path="fixture://review-deferred",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="offer",
            result_summary={"row_count": 1},
        )
        session = _OnCommitCaptureSession()

        monkeypatch.setattr(
            "server.services.import_rebuild_handoff.enqueue_post_import_rebuilds",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
        )

        schedule_review_corrections_after_commit(
            write_session=session,
            entity_type="offer",
            job_id=str(job.id),
            agency_id=agency_id,
            load_outcome=SimpleNamespace(
                listing_wilaya_ids=set(),
                demande_ids=set(),
                demande_client_ids=set(),
                offer_ids={11, 12},
            ),
        )

        callback = cast(Callable[[], None], session.callbacks[0])
        callback()

        job.refresh_from_db()
        assert job.status == ImportJob.Status.READY
        assert job.stage == ImportJob.Stage.REVIEW
        assert (job.result_summary or {}).get("follow_up") == _expected_follow_up(
            state="deferred",
            entities=["offer"],
            success_notification_state="skipped",
            rebuild_state="deferred",
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_distributed_import_job_prefers_demande_batch_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPDF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="demandes.csv",
            file_type="csv",
            source_path="fixture://demandes",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="demande",
            result_summary={
                "row_count": 3,
                "workflow": {
                    "params": {"entity_type": "demande"},
                    "started_at": timezone.now().isoformat(),
                },
            },
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="demande",
            row_start=1,
            row_end=3,
            row_count=3,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
            metrics_payload={
                "created_count": 3,
                "skipped_count": 0,
                "error_count": 0,
                "demande_ids": [21, 22, 23],
                "demande_client_ids": [101, 102, 103],
                "committed_entities": ["demande"],
            },
        )
        captured: dict[str, object] = {"client_calls": []}
        monkeypatch.setattr(
            "server.services.match_jobs.enqueue_rebuild_demande_pairs_batch",
            lambda demande_ids, *, agency_id: captured.update(
                {"demande_ids": list(demande_ids), "agency_id": int(agency_id)}
            ),
        )
        monkeypatch.setattr(
            "server.services.match_jobs.enqueue_rebuild_client_pairs",
            lambda client_id: cast(list[int], captured["client_calls"]).append(int(client_id)),
        )
        monkeypatch.setattr(
            "server.services.import_finalize_service.record_import_success_notification",
            lambda **_kwargs: {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
        )
        monkeypatch.setattr(
            "server.services.import_execution_metrics.record_import_metrics",
            lambda **_kwargs: None,
        )

        result = finalize_distributed_import_job(job=job, user_id=user_id)

        assert result["created_count"] == 3
        assert captured["demande_ids"] == [21, 22, 23]
        assert captured["agency_id"] == agency_id
        assert captured["client_calls"] == []
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_distributed_import_job_defers_follow_up_when_rebuild_handoff_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPFDF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="offers-deferred.csv",
            file_type="csv",
            source_path="fixture://offers-deferred",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="offer",
            result_summary={
                "row_count": 3,
                "workflow": {
                    "params": {"entity_type": "offer"},
                    "started_at": timezone.now().isoformat(),
                },
            },
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="offer",
            row_start=1,
            row_end=3,
            row_count=3,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
            metrics_payload={
                "created_count": 3,
                "skipped_count": 0,
                "error_count": 0,
                "offer_ids": [41, 42, 43],
                "committed_entities": ["offer"],
            },
        )
        monkeypatch.setattr(
            "server.services.match_jobs.enqueue_rebuild_offer_pairs_batch",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
        )
        monkeypatch.setattr(
            "server.services.import_finalize_service.record_import_success_notification",
            lambda **_kwargs: {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
        )
        monkeypatch.setattr(
            "server.services.import_execution_metrics.record_import_metrics",
            lambda **_kwargs: None,
        )

        result = finalize_distributed_import_job(job=job, user_id=user_id)
        job.refresh_from_db()

        assert result["success"] is True
        assert result["follow_up"] == _expected_follow_up(
            state="deferred",
            entities=["offer"],
            success_notification_state="completed",
            rebuild_state="deferred",
        )
        assert job.status == ImportJob.Status.COMPLETED
        assert bool(workflow_payload(job).get("cancel_requested", False)) is False
        assert (job.result_summary or {}).get("follow_up") == result["follow_up"]
        assert workflow_payload(job).get("follow_up") == result["follow_up"]
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_distributed_import_job_aborts_terminal_success_when_notification_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPFND")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="offers-notify-deferred.csv",
            file_type="csv",
            source_path="fixture://offers-notify-deferred",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="offer",
            result_summary={
                "row_count": 2,
                "workflow": {
                    "params": {"entity_type": "offer"},
                    "started_at": timezone.now().isoformat(),
                },
            },
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="offer",
            row_start=1,
            row_end=2,
            row_count=2,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
            metrics_payload={
                "created_count": 2,
                "skipped_count": 0,
                "error_count": 0,
                "offer_ids": [81, 82],
                "committed_entities": ["offer"],
            },
        )
        monkeypatch.setattr(
            "server.services.import_finalize_service.record_import_success_notification",
            lambda **_kwargs: (_ for _ in ()).throw(NotificationPersistenceError("persist failed")),
        )
        monkeypatch.setattr(
            "server.services.import_execution_metrics.record_import_metrics",
            lambda **_kwargs: None,
        )

        with pytest.raises(NotificationPersistenceError):
            finalize_distributed_import_job(job=job, user_id=user_id)

        job.refresh_from_db()

        assert job.status == ImportJob.Status.RUNNING
        assert (job.result_summary or {}).get("follow_up") is None
        assert bool(workflow_payload(job).get("cancel_requested", False)) is False
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_distributed_import_job_persists_review_overflow_as_blocking_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPOF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="overflow.csv",
            file_type="csv",
            source_path="fixture://overflow",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={
                "row_count": 4,
                "workflow": {
                    "params": {"entity_type": "client"},
                    "prepare_counts": {"review_overflow_count": 3, "error_count": 0},
                    "started_at": timezone.now().isoformat(),
                },
            },
        )
        monkeypatch.setattr(
            "server.services.import_finalize_service.emit_import_notification",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_execution_metrics.record_import_metrics",
            lambda **_kwargs: None,
        )

        result = finalize_distributed_import_job(job=job, user_id=user_id)
        job.refresh_from_db()

        assert result["review_overflow_count"] == 3
        assert result["review_total_count"] == 3
        assert result["success"] is False
        assert result["error_count"] == 1
        assert job.status == ImportJob.Status.FAILED
        assert job.stage == ImportJob.Stage.REVIEW
        assert "safely process" in str(job.error_message or "").lower()
        assert int((job.result_summary or {}).get("review_overflow_count", 0) or 0) == 3
        assert int((job.result_summary or {}).get("review_total_count", 0) or 0) == 3
        assert bool((job.result_summary or {}).get("success")) is False
        assert str((job.result_summary or {}).get("review_state", "") or "") == "emergency_overflow"
        assert bool((job.result_summary or {}).get("overflow_blocking", False)) is True
        assert bool((job.result_summary or {}).get("review_disabled", False)) is True
        assert int((job.progress_detail or {}).get("review_overflow_count", 0) or 0) == 3
        assert int((job.progress_detail or {}).get("rows_review", 0) or 0) == 3
        assert (
            "emergency review capacity"
            in " ".join(
                str(item) for item in list((job.result_summary or {}).get("errors", []) or [])
            ).lower()
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_distributed_import_job_fails_when_terminal_errors_remain_without_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPDFL")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="terminal-errors.csv",
            file_type="csv",
            source_path="fixture://terminal-errors",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={
                "row_count": 2,
                "workflow": {
                    "params": {"entity_type": "client"},
                    "prepare_counts": {"review_overflow_count": 0, "error_count": 1},
                    "started_at": timezone.now().isoformat(),
                },
            },
        )
        monkeypatch.setattr(
            "server.services.import_finalize_service.emit_import_notification",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_execution_metrics.record_import_metrics",
            lambda **_kwargs: None,
        )

        result = finalize_distributed_import_job(job=job, user_id=user_id)
        job.refresh_from_db()

        assert result["success"] is False
        assert result["error_count"] >= 1
        assert job.status == ImportJob.Status.FAILED
        assert job.stage == ImportJob.Stage.EXECUTION
        assert bool((job.result_summary or {}).get("success", True)) is False
        assert int((job.result_summary or {}).get("review_total_count", 0) or 0) == 0
        assert "couldn't be imported safely" in str(job.error_message or "").lower()
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_distributed_import_job_is_idempotent_when_already_finalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPFID")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="finalized.csv",
            file_type="csv",
            source_path="fixture://finalized",
            status=ImportJob.Status.COMPLETED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={
                "row_count": 2,
                "success": True,
                "created_count": 2,
                "updated_count": 0,
                "skipped_count": 0,
                "error_count": 0,
                "review_count": 0,
                "review_overflow_count": 0,
                "review_total_count": 0,
                "terminal_reason": "success",
                "workflow": {
                    "params": {"entity_type": "client"},
                    "finalized": True,
                    "status": "completed",
                },
            },
        )
        monkeypatch.setattr(
            "server.services.import_finalize_service.emit_import_notification",
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not notify twice")),
        )

        result = finalize_distributed_import_job(job=job, user_id=user_id)

        assert result == {
            "success": True,
            "created_count": 2,
            "updated_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "review_count": 0,
            "review_overflow_count": 0,
            "review_total_count": 0,
            "follow_up": _expected_follow_up(
                state="completed",
                entities=[],
                success_notification_state="skipped",
                rebuild_state="skipped",
            ),
        }
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_distributed_import_job_does_not_complete_when_cancel_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPFCA")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="cancelled.csv",
            file_type="csv",
            source_path="fixture://cancelled",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={
                "row_count": 2,
                "workflow": {
                    "params": {"entity_type": "client"},
                    "cancel_requested": True,
                    "started_at": timezone.now().isoformat(),
                },
            },
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="client",
            row_start=1,
            row_end=2,
            row_count=2,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
            metrics_payload={
                "created_count": 2,
                "skipped_count": 0,
                "error_count": 0,
                "committed_entities": ["client"],
            },
        )
        monkeypatch.setattr(
            "server.services.import_finalize_service.emit_import_notification",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_execution_metrics.record_import_metrics",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.services.import_rebuild_handoff.enqueue_post_import_rebuilds_for_entities",
            lambda **_kwargs: None,
        )

        finalize_distributed_import_job(job=job, user_id=user_id)
        job.refresh_from_db()

        assert job.status == ImportJob.Status.FAILED
        assert str(job.error_message or "").lower().startswith("this import was cancelled")
        assert (job.result_summary or {}).get("terminal_reason") == "cancelled"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_finalize_job_task_retries_notification_persistence_without_marking_job_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    agency_id, user_id, user = _make_user_and_agency("IMPFTK")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="offers-task-deferred.csv",
            file_type="csv",
            source_path="fixture://offers-task-deferred",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="offer",
            result_summary={
                "row_count": 2,
                "workflow": {
                    "params": {"entity_type": "offer"},
                    "started_at": timezone.now().isoformat(),
                },
            },
        )
        chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.SINGLE,
            entity_type="offer",
            row_start=1,
            row_end=2,
            row_count=2,
        )
        ImportChunkPhase.objects.create(
            chunk=chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.COMPLETED,
            metrics_payload={
                "created_count": 2,
                "skipped_count": 0,
                "error_count": 0,
                "offer_ids": [71, 72],
                "committed_entities": ["offer"],
            },
        )
        failed_marks: list[dict[str, object]] = []
        retry_calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "server.services.import_finalize_service.record_import_success_notification",
            lambda **_kwargs: (_ for _ in ()).throw(NotificationPersistenceError("persist failed")),
        )
        monkeypatch.setattr(
            "server.services.import_execution_metrics.record_import_metrics",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            tasks_import_phase_tasks_module,
            "release_execution_slot",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            tasks_import_phase_tasks_module,
            "dispatch_next_agency_import",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            tasks_import_phase_tasks_module,
            "dispatch_queued_imports",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            tasks_import_phase_tasks_module,
            "mark_distributed_job_failed",
            lambda **kwargs: failed_marks.append(dict(kwargs)),
        )
        monkeypatch.setattr(
            tasks_import_module.import_finalize_job_task,
            "retry",
            lambda **kwargs: retry_calls.append(dict(kwargs))
            or (_ for _ in ()).throw(RuntimeError("retry requested")),
        )

        with pytest.raises(RuntimeError, match="retry requested"):
            tasks_import_module.import_finalize_job_task.run(
                session_id=str(job.id),
                user_id=user_id,
                agency_id=agency_id,
                schema=None,
                correlation_id=None,
            )
        job.refresh_from_db()

        assert failed_marks == []
        assert len(retry_calls) == 1
        assert isinstance(retry_calls[0]["exc"], NotificationPersistenceError)
        assert job.status == ImportJob.Status.RUNNING
        assert bool(workflow_payload(job).get("cancel_requested", False)) is False
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_persist_review_state_clears_stale_db_review_state_when_review_empties() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRCLR")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="stale-review.csv",
            file_type="csv",
            source_path="fixture://stale-review",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 1},
        )
        group = ImportReviewGroup.objects.create(
            job=job,
            group_key="client:phone:0555001111",
            group_kind=ImportReviewGroup.Kind.BUNDLE_ROOT,
            status=ImportReviewGroup.Status.PENDING,
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This line needs review.",
            entity_type="client",
            topology_side="client_side",
            root_identity={"phone": "0555001111"},
            root_label="Stale Client",
            root_row_ordinal=1,
            item_count=1,
            pending_item_count=1,
            blocking_item_count=0,
            suggested_group_action="review_ambiguous",
            search_text="stale client 0555001111",
        )
        ImportReviewItem.objects.create(
            job=job,
            group=group,
            row_ordinal=1,
            entity_type="client",
            topology_side="client_side",
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This line needs review.",
            raw_data={"family_name": "Stale Client", "phone": "0555001111"},
            normalized_data={"family_name": "Stale Client", "phone": "0555001111"},
        )

        persist_review_state(
            job=job,
            review_rows=[],
            progress_detail={"phase": "review", "rows_total": 1},
        )
        job.refresh_from_db()

        assert ImportReviewGroup.objects.filter(job=job).count() == 0
        assert ImportReviewItem.objects.filter(job=job).count() == 0
        assert job.review_rows == []
        assert int((job.progress_detail or {}).get("review_pending_group_count", 0) or 0) == 0
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_apply_item_resolutions_marks_group_partially_resolved_and_keeps_it_pending() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRGRP")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="partial-group.csv",
            file_type="csv",
            source_path="fixture://partial-group",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            result_summary={"row_count": 2},
        )
        group = ImportReviewGroup.objects.create(
            job=job,
            group_key="client:phone:0555009898",
            group_kind=ImportReviewGroup.Kind.BUNDLE_ROOT,
            status=ImportReviewGroup.Status.PENDING,
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This group needs review.",
            entity_type="client",
            topology_side="client_side",
            root_identity={"phone": "0555009898"},
            root_label="Partial Group",
            root_row_ordinal=1,
            item_count=2,
            pending_item_count=2,
            blocking_item_count=0,
            suggested_group_action="update_existing",
            search_text="partial group 0555009898",
        )
        first = ImportReviewItem.objects.create(
            job=job,
            group=group,
            row_ordinal=1,
            entity_type="client",
            topology_side="client_side",
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This line needs review.",
            raw_data={"family_name": "A", "phone": "0555009898"},
            normalized_data={"family_name": "A", "phone": "0555009898"},
        )
        ImportReviewItem.objects.create(
            job=job,
            group=group,
            row_ordinal=2,
            entity_type="client",
            topology_side="client_side",
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This line needs review.",
            raw_data={"family_name": "B", "phone": "0555009898"},
            normalized_data={"family_name": "B", "phone": "0555009898"},
        )

        apply_item_resolutions(
            job=job,
            item_decisions={str(first.id): {"action": "create_new", "entity_type": "client"}},
            skip_item_ids=[],
        )
        group.refresh_from_db()

        assert group.status == ImportReviewGroup.Status.PARTIALLY_RESOLVED
        assert int(group.pending_item_count or 0) == 1
        assert int(group.resolved_item_count or 0) == 1

        groups, _page = paged_review_groups(
            job=job,
            page=1,
            page_size=50,
            issue_group=None,
            search="",
            pending_only=True,
        )

        assert len(groups) == 1
        assert groups[0]["status"] == "partially_resolved"
        assert groups[0]["pending_item_count"] == 1
        assert groups[0]["resolved_item_count"] == 1
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_execute_import_single_entity_clears_stale_db_review_state_when_rerun_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPEXCLR")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="single-clean-rerun.csv",
            file_type="csv",
            source_path="fixture://single-clean-rerun",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 1},
            inference_summary={"final_inference": {"bundle_mode": "single_entity"}},
        )
        persist_review_state(
            job=job,
            review_rows=[
                {
                    "row": 1,
                    "entity_type": "client",
                    "data": {"family_name": "Stale Client", "phone": "0555004444"},
                    "normalized_data": {"family_name": "Stale Client", "phone": "0555004444"},
                    "original": {"family_name": "Stale Client", "phone": "0555004444"},
                    "raw_data": {"family_name": "Stale Client", "phone": "0555004444"},
                    "issue_group": "possible_duplicate",
                    "issue_title": "Possible duplicate",
                    "issue_summary": "This line needs review.",
                    "suggested_action": "review_ambiguous",
                }
            ],
            progress_detail={"phase": "review", "rows_total": 1},
        )

        artifact = PreparedImportArtifact(
            bundle_mode="single_entity",
            total_rows=1,
            current_batch_size=1,
            chunks_total=1,
            entity_type="client",
        )

        monkeypatch.setattr(
            import_executor,
            "load_planned_artifact_checkpoint",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            import_executor,
            "prepare_single_entity_import",
            lambda **_kwargs: artifact,
        )
        monkeypatch.setattr(
            import_executor,
            "plan_single_entity_import",
            lambda **_kwargs: artifact,
        )

        def _load_single_entity_import(**kwargs: object) -> SimpleNamespace:
            result = cast(ImportResult, kwargs["result"])
            result.created_count = 1
            result.created_entity_counts = {"client": 1}
            result.success = True
            return SimpleNamespace(total_db_time=0.0)

        monkeypatch.setattr(
            import_executor,
            "load_single_entity_import",
            _load_single_entity_import,
        )
        monkeypatch.setattr(
            import_executor,
            "persist_planned_artifact_checkpoint",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            import_executor,
            "_clear_planned_checkpoint_best_effort",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            import_executor,
            "record_import_metrics",
            lambda **_kwargs: None,
        )
        success_notifications: list[dict[str, object]] = []
        monkeypatch.setattr(
            "server.services.import_execution_state.record_import_success_notification",
            lambda **kwargs: success_notifications.append(dict(kwargs))
            or {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = import_executor.execute_import(job=job, user_id=user_id)
        job.refresh_from_db()

        assert result.success is True
        assert ImportReviewGroup.objects.filter(job=job).count() == 0
        assert ImportReviewItem.objects.filter(job=job).count() == 0
        assert job.review_rows == []
        assert job.stage == ImportJob.Stage.EXECUTION
        assert job.status == ImportJob.Status.COMPLETED
        assert int(job.progress or 0) == 100
        assert int((job.result_summary or {}).get("created_count", 0) or 0) == 1
        assert int((job.result_summary or {}).get("error_count", 0) or 0) == 0
        assert bool((job.result_summary or {}).get("success", False)) is True
        assert dict((job.result_summary or {}).get("result_entity_counts", {}) or {}) == {
            "client": 1
        }
        assert success_notifications and success_notifications[0]["job_id"] == str(job.id)
        assert (job.result_summary or {}).get("follow_up") == _expected_follow_up(
            state="completed",
            entities=["client"],
            success_notification_state="completed",
            rebuild_state="completed",
        )
        assert int((job.progress_detail or {}).get("review_pending_group_count", 0) or 0) == 0
        assert int((job.progress_detail or {}).get("error_count", 0) or 0) == 0
        assert str((job.progress_detail or {}).get("phase", "") or "") == "done"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_direct_execution_aborts_terminal_success_when_notification_persistence_fails() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPDND")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="direct-notify-deferred.csv",
            file_type="csv",
            source_path="fixture://direct-notify-deferred",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 1},
        )
        artifact = PreparedImportArtifact(
            bundle_mode="single_entity",
            total_rows=1,
            current_batch_size=1,
            chunks_total=1,
            entity_type="client",
        )
        result = ImportResult(
            success=True,
            created_count=1,
            created_entity_counts={"client": 1},
        )
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            "server.services.import_execution_state.record_import_success_notification",
            lambda **_kwargs: (_ for _ in ()).throw(NotificationPersistenceError("persist failed")),
        )

        try:
            with pytest.raises(NotificationPersistenceError):
                import_executor._persist_direct_execution_state(
                    job=job,
                    user_id=user_id,
                    artifact=artifact,
                    result=result,
                    review_rows=[],
                )
            job.refresh_from_db()

            assert job.status == ImportJob.Status.RUNNING
            assert (job.result_summary or {}).get("follow_up") is None
        finally:
            monkeypatch.undo()
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_direct_execution_review_state_marks_job_ready_and_preserves_created_counts() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPDRV")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="direct-review.csv",
            file_type="csv",
            source_path="fixture://direct-review",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 2},
        )
        artifact = PreparedImportArtifact(
            bundle_mode="same_side_bundle",
            total_rows=2,
            current_batch_size=1,
            chunks_total=1,
            entity_type="client",
            root_entity="client",
            child_entity="demande",
        )
        result = ImportResult(
            success=True,
            created_count=1,
            created_entity_counts={"client": 1},
        )

        import_executor._persist_direct_execution_state(
            job=job,
            user_id=user_id,
            artifact=artifact,
            result=result,
            review_rows=[
                {
                    "row": 2,
                    "entity_type": "demande",
                    "data": {"action": "buy"},
                    "original": {"action": "buy"},
                    "normalized_data": {"action": "buy"},
                    "raw_data": {"action": "buy"},
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "This line still needs review.",
                }
            ],
        )
        job.refresh_from_db()

        assert job.status == ImportJob.Status.READY
        assert job.stage == ImportJob.Stage.REVIEW
        assert int((job.result_summary or {}).get("created_count", 0) or 0) == 1
        assert int((job.result_summary or {}).get("review_total_count", 0) or 0) == 1
        assert int((job.progress_detail or {}).get("rows_created", 0) or 0) == 1
        assert int((job.progress_detail or {}).get("rows_review", 0) or 0) == 1
        assert int((job.progress_detail or {}).get("error_count", 0) or 0) == 0
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_direct_execution_persists_terminal_errors_as_failed_without_review() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPDFE")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="direct-errors.csv",
            file_type="csv",
            source_path="fixture://direct-errors",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 2},
        )
        artifact = PreparedImportArtifact(
            bundle_mode="single_entity",
            total_rows=2,
            current_batch_size=1,
            chunks_total=1,
            entity_type="client",
        )
        result = ImportResult(
            success=True,
            created_count=0,
            created_entity_counts={},
            error_count=1,
            errors=[{"row": 2, "errors": ["duplicate phone"]}],
        )

        import_executor._persist_direct_execution_state(
            job=job,
            user_id=user_id,
            artifact=artifact,
            result=result,
            review_rows=[],
        )
        job.refresh_from_db()

        assert result.success is False
        assert job.status == ImportJob.Status.FAILED
        assert int(job.progress or 0) == 100
        assert job.stage == ImportJob.Stage.EXECUTION
        assert int((job.result_summary or {}).get("created_count", 0) or 0) == 0
        assert int((job.result_summary or {}).get("error_count", 0) or 0) == 1
        assert bool((job.result_summary or {}).get("success", True)) is False
        assert int((job.progress_detail or {}).get("error_count", 0) or 0) == 1
        assert "couldn't be imported safely" in str(job.error_message or "").lower()
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_direct_execution_completes_with_attention_when_rows_changed_despite_row_errors() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPDPA")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="direct-partial.csv",
            file_type="csv",
            source_path="fixture://direct-partial",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 2},
        )
        artifact = PreparedImportArtifact(
            bundle_mode="single_entity",
            total_rows=2,
            current_batch_size=1,
            chunks_total=1,
            entity_type="client",
        )
        result = ImportResult(
            success=True,
            created_count=1,
            created_entity_counts={"client": 1},
            error_count=1,
            errors=[{"row": 2, "errors": ["duplicate phone"]}],
        )
        notification_calls: list[dict[str, object]] = []
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            "server.services.import_execution_state.record_import_success_notification",
            lambda **kwargs: notification_calls.append(dict(kwargs))
            or {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
        )

        try:
            import_executor._persist_direct_execution_state(
                job=job,
                user_id=user_id,
                artifact=artifact,
                result=result,
                review_rows=[],
            )
            job.refresh_from_db()

            assert result.success is True
            assert job.status == ImportJob.Status.COMPLETED
            assert job.error_message is None
            assert bool((job.result_summary or {}).get("success", False)) is True
            assert (job.result_summary or {}).get("terminal_reason") == "success"
            assert int((job.result_summary or {}).get("error_count", 0) or 0) == 1
            assert notification_calls and notification_calls[0]["job_id"] == str(job.id)
            assert (job.result_summary or {}).get("follow_up") == _expected_follow_up(
                state="completed",
                entities=["client"],
                success_notification_state="completed",
                rebuild_state="completed",
            )
        finally:
            monkeypatch.undo()
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_direct_execution_persists_zero_change_terminal_contract() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPDZC")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="direct-zero-change.csv",
            file_type="csv",
            source_path="fixture://direct-zero-change",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={"row_count": 3},
        )
        artifact = PreparedImportArtifact(
            bundle_mode="single_entity",
            total_rows=3,
            current_batch_size=1,
            chunks_total=1,
            entity_type="client",
        )
        result = ImportResult(
            success=True,
            created_count=0,
            updated_count=0,
            skipped_count=3,
            created_entity_counts={},
        )
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            "server.services.import_execution_state.record_import_success_notification",
            lambda **_kwargs: {
                "state": "completed",
                "reason_code": "",
                "recovery_owner": "",
            },
        )

        try:
            import_executor._persist_direct_execution_state(
                job=job,
                user_id=user_id,
                artifact=artifact,
                result=result,
                review_rows=[],
            )
            job.refresh_from_db()

            assert job.status == ImportJob.Status.COMPLETED
            assert (job.result_summary or {}).get("terminal_reason") == "zero_change"
            assert bool((job.result_summary or {}).get("result_zero_change", False)) is True
            assert list((job.result_summary or {}).get("result_zero_change_reasons", []) or []) == [
                "all_rows_skipped"
            ]
            assert int((job.result_summary or {}).get("unchanged_count", 0) or 0) == 0
            assert (job.result_summary or {}).get("follow_up") == _expected_follow_up(
                state="completed",
                entities=[],
                success_notification_state="completed",
                rebuild_state="skipped",
            )
        finally:
            monkeypatch.undo()
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_mark_job_failed_clears_stale_review_state_for_direct_execution() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPFDR")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="direct-failure.csv",
            file_type="csv",
            source_path="fixture://direct-failure",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            result_summary={
                "row_count": 1,
                "review_state": "normal",
                "review_total_count": 1,
                "review_pending_group_count": 1,
            },
            progress_detail={
                "phase": "review",
                "review_state": "normal",
                "review_pending_group_count": 1,
            },
            review_rows=[
                {
                    "row": 1,
                    "entity_type": "client",
                    "data": {"family_name": "Stale Direct", "phone": "0555008888"},
                }
            ],
        )
        persist_review_state(
            job=job,
            review_rows=[
                {
                    "row": 1,
                    "entity_type": "client",
                    "data": {"family_name": "Stale Direct", "phone": "0555008888"},
                    "normalized_data": {"family_name": "Stale Direct", "phone": "0555008888"},
                    "original": {"family_name": "Stale Direct", "phone": "0555008888"},
                    "raw_data": {"family_name": "Stale Direct", "phone": "0555008888"},
                    "issue_group": "possible_duplicate",
                    "issue_title": "Possible duplicate",
                    "issue_summary": "This line needs review.",
                    "suggested_action": "review_ambiguous",
                }
            ],
            progress_detail={"phase": "review", "rows_total": 1},
        )

        import_executor._mark_job_failed(job, RuntimeError("boom"))
        job.refresh_from_db()

        assert job.status == ImportJob.Status.FAILED
        assert int(job.progress or 0) == 100
        assert job.stage == ImportJob.Stage.EXECUTION
        assert ImportReviewGroup.objects.filter(job=job).count() == 0
        assert ImportReviewItem.objects.filter(job=job).count() == 0
        assert list(job.review_rows or []) == []
        assert str((job.result_summary or {}).get("review_state", "") or "") == "none"
        assert int((job.result_summary or {}).get("review_total_count", 0) or 0) == 0
        assert str((job.progress_detail or {}).get("review_state", "") or "") == "none"
        assert int((job.progress_detail or {}).get("review_pending_group_count", 0) or 0) == 0
        assert job.error_message == "We couldn't finish this import yet. Please try again."
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_execute_view_returns_queued_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPVQ")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="queued.csv",
            file_type="csv",
            source_path="fixture://queued-view",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            result_summary={"row_count": 2},
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.admit_import_execute",
            lambda **_kwargs: SimpleNamespace(
                allowed=True,
                retry_after=0,
                degraded=False,
                execution_profile="green",
                queue_on_pressure=False,
            ),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.initialize_distributed_workflow",
            lambda **_kwargs: ({"params": {}}, False),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.claim_execution_or_queue",
            lambda *_args, **_kwargs: QueueClaimResult(
                status="queued",
                queue_position=1,
                agency_queue_depth=1,
            ),
        )
        monkeypatch.setattr(
            "server.services.import_status_policy.resolve_hub_runtime_profile",
            lambda: SimpleNamespace(
                effective_limits=lambda: SimpleNamespace(polling_interval_seconds=1.0)
            ),
        )

        request = APIRequestFactory().post(
            "/api/v1/import/execute/",
            {
                "session_id": str(job.id),
                "column_mapping": {"family_name": "family_name", "phone": "phone"},
                "entity_type": "client",
                "duplicate_strategy": "review",
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_execute(request)

        assert response.status_code == 202
        assert response.data["status"] == "queued"
        assert response.data["task_id"] == str(job.id)
        assert response.data["queue_position"] == 1
        assert response.data["agency_queue_depth"] == 1
        assert response.data["execution_profile"] == "green"
        assert response.data["poll_after_ms"] == 1000
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_execute_view_returns_429_when_agency_queue_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPVF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="full.csv",
            file_type="csv",
            source_path="fixture://full-view",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            result_summary={"row_count": 2},
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.admit_import_execute",
            lambda **_kwargs: SimpleNamespace(
                allowed=True,
                retry_after=0,
                degraded=False,
                execution_profile="green",
                queue_on_pressure=False,
            ),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.initialize_distributed_workflow",
            lambda **_kwargs: ({"params": {}}, False),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.claim_execution_or_queue",
            lambda *_args, **_kwargs: QueueClaimResult(
                status="full",
                queue_position=0,
                agency_queue_depth=1,
            ),
        )

        request = APIRequestFactory().post(
            "/api/v1/import/execute/",
            {
                "session_id": str(job.id),
                "column_mapping": {"family_name": "family_name", "phone": "phone"},
                "entity_type": "client",
                "duplicate_strategy": "review",
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_execute(request)

        assert response.status_code == 429
        assert response.data["code"] == "IMPORT_AGENCY_QUEUE_FULL"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_execute_view_recomputes_stale_manual_mapping_flags() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPMM")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="manual-map.csv",
            file_type="csv",
            source_path="fixture://manual-map",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(["A", "B"]),
            column_mapping={"family_name": "A", "phone": "B"},
            inference_summary={
                "manual_mapping_required": True,
                "manual_mapping_reasons": ["Low-confidence file semantics."],
                "final_inference": {"bundle_mode": "single_entity"},
            },
            result_summary={"row_count": 2},
        )
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            "server.api.views_import_execute.admit_import_execute",
            lambda **_kwargs: SimpleNamespace(
                allowed=True,
                retry_after=0,
                degraded=False,
                execution_profile="green",
                queue_on_pressure=False,
            ),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.initialize_distributed_workflow",
            lambda **_kwargs: ({"params": {}}, False),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.claim_execution_or_queue",
            lambda *_args, **_kwargs: QueueClaimResult(
                status="queued",
                queue_position=1,
                agency_queue_depth=1,
            ),
        )

        request = APIRequestFactory().post(
            "/api/v1/import/execute/",
            {
                "session_id": str(job.id),
                "column_mapping": {"family_name": "A", "phone": "B"},
                "entity_type": "client",
                "duplicate_strategy": "review",
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_execute(request)
        job.refresh_from_db()

        assert response.status_code == 202
        assert response.data["status"] == "queued"
        assert bool((job.inference_summary or {}).get("manual_mapping_required", True)) is False
    finally:
        monkeypatch.undo()
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_execute_view_blocks_child_only_requests_import() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPXO")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="requests-only.csv",
            file_type="csv",
            source_path="fixture://requests-only-execute",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="demande",
            detected_columns=_detected_columns(["action", "type", "budget_min"]),
            column_mapping={"action": "action", "type": "type", "budget_min": "budget_min"},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": "client_side",
                    "detected_entity": "demande",
                }
            },
            result_summary={"row_count": 2},
        )

        request = APIRequestFactory().post(
            "/api/v1/import/execute/",
            {
                "session_id": str(job.id),
                "column_mapping": {"action": "action", "type": "type", "budget_min": "budget_min"},
                "entity_type": "demande",
                "duplicate_strategy": "review",
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_execute(request)

        assert response.status_code == 409
        assert (
            "requests-only files aren't supported" in str(response.data.get("detail", "")).lower()
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_status_view_skips_budget_snapshot_for_completed_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPVS")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="done.csv",
            file_type="csv",
            source_path="fixture://status-view",
            status=ImportJob.Status.COMPLETED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="offer",
            detected_columns=_detected_columns(["listing_id", "budget"]),
            column_mapping={"listing_id": "listing_id", "budget": "budget"},
            progress=100,
            progress_detail={"rows_total": 250, "phase": "executing"},
            result_summary={"row_count": 250, "created_count": 250},
        )
        monkeypatch.setattr(
            "server.services.import_status_api_facade.tenant_resource_governor.budget_state_snapshot",
            lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("budget snapshot should not be called")
            ),
        )
        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["status"] == "completed"
        assert response.data["poll_after_ms"] == 0
        assert response.data["tenant_budget_remaining"] == 0
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_status_payload_uses_cached_agency_queue_depth_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPVQ")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="queued-status.csv",
            file_type="csv",
            source_path="fixture://queued-status",
            status=ImportJob.Status.QUEUED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            progress=0,
            progress_detail={"phase": "queued"},
            result_summary={"row_count": 2},
        )
        snapshot = SimpleNamespace(
            visible_review_count=0,
            pending_group_count=0,
            conflict_count=0,
            issue_counts={},
        )
        monkeypatch.setattr(
            "server.services.import_status_api_facade.workflow_payload",
            lambda _session: {
                "agency_queue_depth": 7,
                "execution_profile": "green",
                "cancel_requested": False,
            },
        )
        monkeypatch.setattr(
            "server.services.import_status_api_facade.ensure_review_state",
            lambda _session: snapshot,
        )
        monkeypatch.setattr(
            "server.services.import_status_api_facade.execution_health_snapshot",
            lambda _session: {},
        )
        monkeypatch.setattr(
            "server.services.import_status_api_facade.queue_position_for_job",
            lambda _session: 1,
        )
        monkeypatch.setattr(
            "server.services.import_status_api_facade.tenant_resource_governor.budget_state_snapshot",
            lambda **_kwargs: {"budgets": {"import_execute": {str(agency_id): {"tokens": 3}}}},
        )
        monkeypatch.setattr(
            "server.services.import_status_api_facade._live_agency_queue_depth",
            lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("agency queue depth COUNT should not run when cached")
            ),
        )

        payload = import_status_api_facade.build_import_status_payload(
            session=job,
            agency_id=agency_id,
        )

        assert payload["status"] == "queued"
        assert payload["agency_queue_depth"] == 7
        assert payload["queue_position"] == 1
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_single_entity_short_circuits_early_review_before_dedup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPEARLY")
    csv_path = tmp_path / "prepare-review-early.csv"
    headers = ["family_name", "phone", "status"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Early Review", "0555007001", "active"])

    artifact = None
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://prepare-review-early",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 1},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        monkeypatch.setattr(
            "server.services.import_prepare_single_flow.apply_row_recovery",
            lambda **kwargs: SimpleNamespace(
                needs_review=True,
                data=dict(kwargs["normalized"].data),
                remarks=["Needs early review"],
                review_fields=[],
                recoverability_class="review_recoverable",
                recovered_fields=[],
                recovery_candidates=[],
                blocking_reasons=[],
            ),
        )
        monkeypatch.setattr(
            "server.services.import_prepare_single_flow.remember_root_key",
            lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("early review rows should not enter root-key dedup")
            ),
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_single_entity_import(
                job=job,
                user_id=user_id,
                entity_type="client",
                skip_rows=0,
                skip_review_rows=False,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact is not None
        assert result.skipped_count == 1
        assert result.error_count == 0
        assert len(review_rows) == 1
        assert "Needs early review" in list(review_rows[0].get("remarks", []) or [])
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_prepare_single_entity_routes_late_review_to_errors_when_review_rows_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPLATE")
    csv_path = tmp_path / "prepare-review-late.csv"
    headers = ["family_name", "phone", "status"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Late Review", "0555007002", "active"])

    artifact = None
    remember_calls: list[int] = []
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://prepare-review-late",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping={header: header for header in headers},
            result_summary={"row_count": 1},
        )
        review_rows: list[dict[str, object]] = []
        result = ImportResult(success=False)
        monkeypatch.setattr(
            "server.services.import_prepare_single_flow.apply_row_recovery",
            lambda **kwargs: SimpleNamespace(
                needs_review=True,
                data=dict(kwargs["normalized"].data),
                remarks=["Needs late review"],
                review_fields=[],
                recoverability_class="review_recoverable",
                recovered_fields=[],
                recovery_candidates=[],
                blocking_reasons=[],
            ),
        )
        monkeypatch.setattr(
            "server.services.import_prepare_single_flow.remember_root_key",
            lambda **_kwargs: remember_calls.append(1)
            or SimpleNamespace(is_duplicate=False, key="", winner_row=0),
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            artifact = prepare_single_entity_import(
                job=job,
                user_id=user_id,
                entity_type="client",
                skip_rows=0,
                skip_review_rows=True,
                duplicate_strategy="review",
                corrections=None,
                review_rows=review_rows,
                result=result,
                download_to_temp_fn=lambda *_args, **_kwargs: csv_path,
            )

        assert artifact is not None
        assert remember_calls == [1]
        assert review_rows == []
        assert result.skipped_count == 0
        assert result.error_count == 1
        assert result.errors == [{"row": 1, "errors": ["Needs late review"]}]
        assert result.dead_letter_summary["blocking_discarded"] == 1
    finally:
        if artifact is not None:
            if artifact.spool_dir is not None:
                shutil.rmtree(artifact.spool_dir, ignore_errors=True)
            if artifact.temp_path is not None:
                artifact.temp_path.unlink(missing_ok=True)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_status_view_projects_failed_when_terminal_errors_exist_without_review() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPVF2")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="status-failed.csv",
            file_type="csv",
            source_path="fixture://status-failed",
            status=ImportJob.Status.COMPLETED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            progress=63,
            progress_detail={"rows_total": 5, "phase": "done", "error_count": 1},
            result_summary={
                "row_count": 5,
                "created_count": 4,
                "error_count": 1,
                "success": False,
                "review_total_count": 0,
            },
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["status"] == "failed"
        assert response.data["stage"] == "done"
        assert response.data["progress"] == 100
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_complete_returns_admission_mode_and_profile_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPVC")
    try:
        monkeypatch.setattr(
            "server.api.views_import_upload.admit_import_parse",
            lambda **_kwargs: SimpleNamespace(
                allowed=True,
                retry_after=0,
                degraded=False,
                execution_profile="yellow",
                admission_mode="normal",
                pressure_reason="token_bucket",
            ),
        )
        monkeypatch.setattr(
            "server.api.views_import_upload.complete_presigned_upload",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "server.api.views_import_upload.import_parse_task.delay",
            lambda **_kwargs: SimpleNamespace(id="parse-task-1"),
        )
        monkeypatch.setattr(
            "server.api.views_import_upload.register_task",
            lambda *_args, **_kwargs: None,
        )

        request = APIRequestFactory().post(
            "/api/v1/import/complete/",
            {
                "storage_id": str(uuid.uuid4()),
                "filename": "contract.csv",
                "entity_type": "client",
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_complete(request)

        assert response.status_code == 202
        assert response.data["poll_after_ms"] == 150
        assert response.data["admission_mode"] == "normal"
        assert response.data["execution_profile_hint"] == "yellow"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_upload_returns_admission_mode_and_profile_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPVU")
    try:
        monkeypatch.setenv("IMMOAPP_ALLOW_PROXY_UPLOADS", "1")
        monkeypatch.setattr(
            "server.api.views_import_upload.admit_import_parse",
            lambda **_kwargs: SimpleNamespace(
                allowed=True,
                retry_after=0,
                degraded=True,
                execution_profile="red",
                admission_mode="degraded",
                pressure_reason="degraded_parse_fallback",
            ),
        )
        monkeypatch.setattr(
            "server.api.views_import_upload.store_fileobj",
            lambda **_kwargs: uuid.uuid4(),
        )
        monkeypatch.setattr(
            "server.api.views_import_upload.import_parse_task.delay",
            lambda **_kwargs: SimpleNamespace(id="parse-task-upload-1"),
        )
        monkeypatch.setattr(
            "server.api.views_import_upload.register_task",
            lambda *_args, **_kwargs: None,
        )

        upload = SimpleUploadedFile(
            "proxy.csv",
            b"family_name,phone\nAlice,0555004001\n",
            content_type="text/csv",
        )
        request = APIRequestFactory().post(
            "/api/v1/import/upload/",
            {"file": upload},
            format="multipart",
        )
        force_authenticate(request, user=user)

        response = import_upload(request)

        assert response.status_code == 202
        assert response.data["poll_after_ms"] == 150
        assert response.data["admission_mode"] == "degraded"
        assert response.data["execution_profile_hint"] == "red"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)
