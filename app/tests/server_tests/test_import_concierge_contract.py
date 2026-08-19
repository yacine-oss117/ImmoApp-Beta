from __future__ import annotations

import csv
from pathlib import Path
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

from core.importer.security import import_security_limits  # noqa: E402
from server.api import tasks_import_review as tasks_import_review_module  # noqa: E402
from server.api.views_import_execute import import_status  # noqa: E402
from server.api.views_import_preview import import_preview  # noqa: E402
from server.api.views_import_review import (  # noqa: E402
    import_review,
    import_review_submit,
)
from server.api.views_import_upload import import_presign  # noqa: E402
from server.imports.models import (  # noqa: E402
    ImportJob,
    ImportReviewGroup,
    ImportReviewItem,
)
from server.pg.schema import ensure_schema  # noqa: E402
from server.services.import_chunk_workflow import workflow_payload  # noqa: E402
from server.services.import_review_row_actions import ReviewResolutionState  # noqa: E402
from server.services.import_review_submit_service import (  # noqa: E402
    ImportReviewSubmitConflictError,
    run_review_submit_task,
)
from server.services.storage_errors import StorageNotReadyError  # noqa: E402


def _write_client_demande_bundle(path: Path) -> list[str]:
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
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(["Yacine", "0555 001 001", "active", "", "", "", "", "", "", "", "", ""])
        writer.writerow(
            [
                "Yacine",
                "0555 001 001",
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
    return headers


def _write_partial_client_demande_bundle(path: Path) -> list[str]:
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_max",
        "surface_min",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            ["Nadia", "0555 111 222", "active", "buy", "apartment", "16", "Hydra", "1500000", "80"]
        )
    return headers


def _write_combined_client_demande_bundle(path: Path) -> list[str]:
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
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            [
                "Yacine",
                "0555 001 001",
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
            ]
        )
        writer.writerow(
            [
                "Yacine",
                "0555 001 001",
                "active",
                "buy",
                "apartment",
                "16",
                "El Biar",
                "1300000",
                "2600000",
                "70",
                "140",
                "3",
            ]
        )
        writer.writerow(
            [
                "Noura",
                "0600 000 004",
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
            ]
        )
    return headers


def _write_many_client_rows(path: Path, *, count: int) -> list[str]:
    headers = ["family_name", "phone", "status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for index in range(count):
            letters = chr(65 + (index % 26)) * (1 + (index // 26))
            writer.writerow([f"Client{letters}", f"055500{index + 1000:04d}", "active"])
    return headers


def test_import_preview_returns_concierge_summary_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCP")
    csv_path = tmp_path / "bundle_preview.csv"
    headers = _write_client_demande_bundle(csv_path)
    mapping = {header: header for header in headers}
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-preview",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping=mapping,
            result_summary={"row_count": 2},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
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
                "column_mapping": mapping,
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == 200
        assert response.data["entity_counts"]["client"] == 1
        assert response.data["entity_counts"]["demande"] == 1
        assert response.data["auto_fix_summary"]["grouped_related_rows"] == 1
        assert "price_dialect_summary" in response.data
        assert set(response.data["auto_fix_summary"]) == {
            "phone_format_fixed",
            "name_case_fixed",
            "location_normalized",
            "grouped_related_rows",
            "other_auto_fixes",
        }
        assert set(response.data["attention_summary"]) == {
            "needs_attention",
            "blocking",
            "possible_duplicates",
            "missing_information",
        }
        job.refresh_from_db()
        assert job.column_mapping == mapping
        assert job.detected_entity == "client"
        assert len(job.preview_rows or []) == 2
        assert job.preview_rows[0]["entity_type"] == "client"
        assert job.preview_rows[1]["entity_type"] == "demande"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_preview_keeps_same_side_demande_rows_auto_recoverable_with_partial_ranges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPPR")
    csv_path = tmp_path / "partial_bundle_preview.csv"
    headers = _write_partial_client_demande_bundle(csv_path)
    mapping = {header: header for header in headers}
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://partial-bundle-preview",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping=mapping,
            result_summary={"row_count": 1},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
                    "file_model_hint": "client_lead_sheet",
                    "dominant_side": "client_side",
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
                "column_mapping": mapping,
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == 200
        assert response.data["recoverability_summary"]["blocking"] == 0
        assert len(response.data["preview_rows"]) == 1
        preview_row = response.data["preview_rows"][0]
        assert preview_row["entity_type"] == "demande"
        assert preview_row["blocking_reasons"] == []
        assert preview_row["normalized"]["budget_min"] == 0.0
        assert preview_row["normalized"]["budget_max"] == 1500000.0
        assert preview_row["normalized"]["surface_min"] == 80.0
        assert preview_row["normalized"]["surface_max"] == 80.0
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_preview_counts_combined_bundle_rows_as_roots_and_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCB")
    csv_path = tmp_path / "bundle_preview_combined.csv"
    headers = _write_combined_client_demande_bundle(csv_path)
    mapping = {header: header for header in headers}
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-preview-combined",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping=mapping,
            result_summary={"row_count": 3},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
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
                "column_mapping": mapping,
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == 200
        assert response.data["entity_counts"]["client"] == 2
        assert response.data["entity_counts"]["demande"] == 3
        assert response.data["auto_fix_summary"]["grouped_related_rows"] == 3
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_preview_summaries_cover_rows_beyond_sample_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCL")
    csv_path = tmp_path / "many_clients_preview.csv"
    headers = _write_many_client_rows(csv_path, count=30)
    mapping = {header: header for header in headers}
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://many-clients-preview",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(headers),
            column_mapping=mapping,
            result_summary={"row_count": 30},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
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
                "column_mapping": mapping,
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == 200
        assert len(response.data["preview_rows"]) == import_security_limits().preview_limit_default
        assert response.data["entity_counts"]["client"] == 30
        assert response.data["stats"]["valid"] == 30
        assert response.data["normalization_summary"]["rows_clean"] == 30
        assert response.data["recoverability_summary"]["auto_recoverable"] == 30
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_preview_blocks_requests_only_imports() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPPD")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="requests-only.csv",
            file_type="csv",
            source_path="fixture://requests-only",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="demande",
            detected_columns=_detected_columns(["action", "type", "budget_min"]),
            column_mapping={
                "action": "action",
                "type": "type",
                "budget_min": "budget_min",
            },
            result_summary={"row_count": 3},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": "client_side",
                    "detected_entity": "demande",
                }
            },
        )

        request = APIRequestFactory().post(
            "/api/v1/import/preview/",
            {
                "session_id": str(job.id),
                "entity_type": "demande",
                "column_mapping": {
                    "action": "action",
                    "type": "type",
                    "budget_min": "budget_min",
                },
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == 409
        assert (
            "requests-only files aren't supported" in str(response.data.get("detail", "")).lower()
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_status_returns_preview_and_result_summary_fields() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCS")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="status.csv",
            file_type="csv",
            source_path="fixture://status",
            status=ImportJob.Status.COMPLETED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            preview_rows=[
                {
                    "row_num": 1,
                    "entity_type": "client",
                    "original": {"family_name": "yacine", "phone": "0555 001 001"},
                    "normalized": {"family_name": "Yacine", "phone": "0555001001"},
                    "needs_review": False,
                    "errors": [],
                    "recovered_fields": [{"field": "phone"}],
                },
                {
                    "row_num": 2,
                    "entity_type": "demande",
                    "original": {"locations": "Hydra"},
                    "normalized": {"locations": "Hydra"},
                    "needs_review": False,
                    "errors": [],
                    "recovered_fields": [{"field": "locations"}],
                },
            ],
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
            progress=100,
            progress_detail={"phase": "done", "rows_total": 2},
            result_summary={
                "row_count": 2,
                "created_count": 2,
                "updated_count": 0,
                "result_entity_counts": {"client": 1, "demande": 1},
                "result_auto_fix_summary": {"phone_format_fixed": 1},
            },
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["preview_entity_counts"]["client"] == 1
        assert response.data["preview_entity_counts"]["demande"] == 1
        assert response.data["preview_auto_fix_summary"]["phone_format_fixed"] == 1
        assert response.data["preview_auto_fix_summary"]["location_normalized"] == 1
        assert response.data["result_entity_counts"]["client"] == 1
        assert response.data["result_entity_counts"]["demande"] == 1
        assert response.data["created_count"] == 2
        assert response.data["updated_count"] == 0
        assert response.data["error_count"] == 0
        assert set(response.data["result_attention_summary"]) == {
            "needs_attention",
            "blocking",
            "possible_duplicates",
            "missing_information",
        }
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_status_preserves_full_parse_inference_surface() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPFI")
    try:
        inference_summary = {
            "final_inference": {
                "bundle_mode": "same_side_bundle",
                "topology_side_hint": "client_side",
                "file_model_hint": "client_lead_sheet",
                "dominant_side": "client_side",
                "dominant_side_confidence": 0.98,
                "detected_entity": "client",
            },
            "manual_mapping_required": False,
            "manual_mapping_reasons": [],
            "sheet_profiles": [{"sheet_name": "Sheet1", "confidence": 0.91}],
            "column_semantic_profiles": [
                {
                    "header": "Budget max/Prix (DZD)",
                    "detected_type": "price",
                    "detected_role": "child_budget_max",
                    "side_prior": "client_root",
                    "confidence": 0.88,
                }
            ],
            "agency_profile_hints_used": {"header_vocab": {"budget max/prix (dzd)": "price"}},
            "price_dialect_summary": {
                "dominant_dialect": "raw_dzd",
                "ambiguous_price_row_count": 3,
            },
        }
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="parse-ready.xlsx",
            file_type="excel",
            source_path="fixture://parse-ready",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=_detected_columns(["Nom complet / Client", "Budget max/Prix (DZD)"]),
            column_mapping={
                "family_name": "Nom complet / Client",
                "budget_max": "Budget max/Prix (DZD)",
            },
            preview_rows=[{"Nom complet / Client": "Nadia", "Budget max/Prix (DZD)": "1.5M"}],
            inference_summary=inference_summary,
            progress=100,
            progress_detail={"phase": "mapping", "rows_total": 1},
            result_summary={"row_count": 1},
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["inference_summary"]["final_inference"]["file_model_hint"] == (
            "client_lead_sheet"
        )
        assert response.data["inference_summary"]["price_dialect_summary"] == {
            "dominant_dialect": "raw_dzd",
            "ambiguous_price_row_count": 3,
        }
        assert response.data["column_mapping"] == {
            "family_name": "Nom complet / Client",
            "budget_max": "Budget max/Prix (DZD)",
        }
        assert response.data["price_dialect_summary"] == {
            "dominant_dialect": "raw_dzd",
            "ambiguous_price_row_count": 3,
        }
        assert response.data["sheet_profiles"] == [{"sheet_name": "Sheet1", "confidence": 0.91}]
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_status_does_not_treat_auto_grouped_skips_as_attention() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSK")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="status-auto-skip.csv",
            file_type="csv",
            source_path="fixture://status-auto-skip",
            status=ImportJob.Status.COMPLETED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            progress=100,
            progress_detail={"phase": "done", "rows_total": 3, "error_count": 0},
            result_summary={
                "row_count": 3,
                "created_count": 2,
                "updated_count": 0,
                "skipped_count": 1,
                "error_count": 0,
                "dead_letter_summary": {
                    "auto_skipped": 1,
                    "human_skipped": 0,
                    "blocking_discarded": 0,
                },
                "result_entity_counts": {"client": 1, "demande": 1},
            },
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["status"] == "completed"
        assert response.data["result_attention_summary"]["needs_attention"] == 0
        assert response.data["result_attention_summary"]["blocking"] == 0
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_status_exposes_review_overflow_counts_and_attention() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPOV")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="status-overflow.csv",
            file_type="csv",
            source_path="fixture://status-overflow",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            review_rows=[
                {
                    "row": 14,
                    "entity_type": "client",
                    "original": {"family_name": "Yacine", "phone": "0555001001"},
                    "data": {"family_name": "Yacine", "phone": "0555001001"},
                    "candidate_matches": [{"id": 1, "label": "Yacine"}],
                    "review_fields": [{"field": "phone", "remark": "duplicate"}],
                    "remarks": ["Possible duplicate"],
                }
            ],
            progress_detail={
                "phase": "review",
                "rows_total": 5,
                "review_overflow_count": 4,
            },
            result_summary={"row_count": 5, "review_overflow_count": 4},
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["status"] == "failed"
        assert response.data["stage"] == "review"
        assert response.data["review_count"] == 1
        assert response.data["review_overflow_count"] == 4
        assert response.data["review_total_count"] == 5
        assert response.data["review_state"] == "emergency_overflow"
        assert response.data["overflow_blocking"] is True
        assert response.data["review_disabled"] is True
        assert response.data["result_attention_summary"]["needs_attention"] == 5
        assert response.data["result_attention_summary"]["blocking"] == 4
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_status_reports_zero_change_terminal_reason_and_reasons() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPZC")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="status-zero-change.csv",
            file_type="csv",
            source_path="fixture://status-zero-change",
            status=ImportJob.Status.COMPLETED,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            progress=100,
            progress_detail={"phase": "done", "rows_total": 3},
            result_summary={
                "row_count": 3,
                "created_count": 0,
                "updated_count": 0,
                "skipped_count": 3,
                "error_count": 0,
                "success": True,
            },
        )

        request = APIRequestFactory().get(f"/api/v1/import/status/{job.id}/")
        force_authenticate(request, user=user)

        response = import_status(request, str(job.id))

        assert response.status_code == 200
        assert response.data["status"] == "completed"
        assert response.data["terminal_reason"] == "zero_change"
        assert response.data["result_zero_change"] is True
        assert response.data["result_zero_change_reasons"] == ["all_rows_skipped"]
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_returns_issue_metadata_for_each_row() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPCR")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review.csv",
            file_type="csv",
            source_path="fixture://review",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            review_rows=[
                {
                    "row_num": 14,
                    "entity_type": "client",
                    "original": {"family_name": "Yacine", "phone": "0555001001"},
                    "data": {"family_name": "Yacine", "phone": "0555001001"},
                    "candidate_matches": [{"id": 1, "label": "Yacine"}],
                    "review_fields": [{"field": "phone", "remark": "duplicate"}],
                    "remarks": ["Possible duplicate"],
                },
                {
                    "row_num": 15,
                    "entity_type": "demande",
                    "original": {"locations": ""},
                    "data": {"locations": ""},
                    "review_fields": [{"field": "locations", "remark": "missing"}],
                    "remarks": ["Missing location"],
                },
            ],
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
        )

        request = APIRequestFactory().get(f"/api/v1/import/{job.id}/review/")
        force_authenticate(request, user=user)

        response = import_review(request, str(job.id))

        assert response.status_code == 200
        assert response.data["review_count"] == 2
        assert len(response.data["review_groups"]) == 2
        assert len(response.data["review_rows"]) == 1
        first = response.data["review_rows"][0]
        assert first["issue_group"] == "possible_duplicate"
        assert first["issue_title"] == "Possible duplicate"
        assert "existing record" in first["issue_summary"].lower()
        assert response.data["review_groups"][1]["issue_group"] == "unclear_location"
        assert response.data["review_groups"][1]["issue_title"] == "Location needs checking"
        assert "location" in response.data["review_groups"][1]["issue_summary"].lower()
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_exposes_review_overflow_counts() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRO")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-overflow.csv",
            file_type="csv",
            source_path="fixture://review-overflow",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            review_rows=[
                {
                    "row": 14,
                    "entity_type": "client",
                    "original": {"family_name": "Yacine", "phone": "0555001001"},
                    "data": {"family_name": "Yacine", "phone": "0555001001"},
                    "review_fields": [{"field": "phone", "remark": "duplicate"}],
                    "remarks": ["Possible duplicate"],
                },
                {
                    "row": 15,
                    "entity_type": "client",
                    "original": {"family_name": "Noura", "phone": "0600000004"},
                    "data": {"family_name": "Noura", "phone": "0600000004"},
                    "review_fields": [{"field": "phone", "remark": "duplicate"}],
                    "remarks": ["Possible duplicate"],
                },
            ],
            progress_detail={"phase": "review", "review_overflow_count": 3},
            result_summary={"review_overflow_count": 3},
        )

        request = APIRequestFactory().get(f"/api/v1/import/{job.id}/review/")
        force_authenticate(request, user=user)

        response = import_review(request, str(job.id))

        assert response.status_code == 200
        assert response.data["review_count"] == 2
        assert response.data["review_overflow_count"] == 3
        assert response.data["review_total_count"] == 5
        assert response.data["review_state"] == "emergency_overflow"
        assert response.data["overflow_blocking"] is True
        assert response.data["review_disabled"] is True
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_exposes_group_apply_metadata() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRG")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-groups.csv",
            file_type="csv",
            source_path="fixture://review-groups",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
        )
        group = ImportReviewGroup.objects.create(
            job=job,
            group_key="client:phone:0555001001",
            group_kind=ImportReviewGroup.Kind.BUNDLE_ROOT,
            status=ImportReviewGroup.Status.PENDING,
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This root needs review.",
            entity_type="client",
            topology_side="client_side",
            root_identity={"phone": "0555001001"},
            root_label="Yacine",
            root_row_ordinal=1,
            item_count=2,
            pending_item_count=2,
            blocking_item_count=0,
            suggested_group_action="update_existing",
            apply_to_all_allowed=True,
            apply_to_all_count=2,
            consistent_existing_id=42,
            resolution_template={"action": "update_existing", "existing_id": 42},
            resolved_item_count=0,
            search_text="Yacine 0555001001",
            metadata={"sample_rows": [1, 2]},
        )
        ImportReviewItem.objects.create(
            job=job,
            group=group,
            row_ordinal=1,
            entity_type="client",
            topology_side="client_side",
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This looks very close to an existing record.",
            suggested_action="update_existing",
            suggested_existing_id=42,
            suggested_confidence=0.95,
            raw_data={"family_name": "Yacine", "phone": "0555001001"},
            normalized_data={"family_name": "Yacine", "phone": "0555001001"},
            group_resolvable=True,
            resolution_source="",
            root_identity_snapshot={"phone": "0555001001"},
            candidate_matches=[{"id": 42, "row_version": 3}],
        )
        ImportReviewItem.objects.create(
            job=job,
            group=group,
            row_ordinal=2,
            entity_type="client",
            topology_side="client_side",
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This looks very close to an existing record.",
            suggested_action="update_existing",
            suggested_existing_id=42,
            suggested_confidence=0.93,
            raw_data={"family_name": "Yacine", "phone": "0555001001"},
            normalized_data={"family_name": "Yacine", "phone": "0555001001"},
            group_resolvable=True,
            resolution_source="",
            root_identity_snapshot={"phone": "0555001001"},
            candidate_matches=[{"id": 42, "row_version": 3}],
        )

        request = APIRequestFactory().get(f"/api/v1/import/{job.id}/review/")
        force_authenticate(request, user=user)

        response = import_review(request, str(job.id))

        assert response.status_code == 200
        assert response.data["group_apply_supported"] is True
        assert response.data["review_groups"][0]["apply_to_all_allowed"] is True
        assert response.data["review_groups"][0]["apply_to_all_count"] == 2
        assert response.data["review_groups"][0]["consistent_existing_id"] == 42
        assert response.data["review_items"][0]["group_resolvable"] is True
        assert response.data["review_items"][0]["effective_action"] == "update_existing"
        assert response.data["review_rows"][0]["group_key"] == "client:phone:0555001001"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_honors_requested_items_mode() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRMI")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-items.csv",
            file_type="csv",
            source_path="fixture://review-items",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
        )
        group = ImportReviewGroup.objects.create(
            job=job,
            group_key="client:phone:0555002001",
            group_kind=ImportReviewGroup.Kind.BUNDLE_ROOT,
            status=ImportReviewGroup.Status.PENDING,
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This group needs review.",
            entity_type="client",
            topology_side="client_side",
            root_identity={"phone": "0555002001"},
            root_label="Items Mode",
            root_row_ordinal=1,
            item_count=1,
            pending_item_count=1,
            blocking_item_count=0,
            suggested_group_action="update_existing",
            search_text="items mode 0555002001",
        )
        ImportReviewItem.objects.create(
            job=job,
            group=group,
            row_ordinal=1,
            entity_type="client",
            topology_side="client_side",
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This looks close to an existing record.",
            raw_data={"family_name": "Items Mode", "phone": "0555002001"},
            normalized_data={"family_name": "Items Mode", "phone": "0555002001"},
        )

        request = APIRequestFactory().get(f"/api/v1/import/{job.id}/review/?mode=items")
        force_authenticate(request, user=user)

        response = import_review(request, str(job.id))

        assert response.status_code == 200
        assert response.data["review_mode"] == "items"
        assert response.data["review_filters"]["mode"] == "items"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_falls_back_to_first_visible_group_when_requested_group_is_missing() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-fallback.csv",
            file_type="csv",
            source_path="fixture://review-fallback",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
        )
        first_group = ImportReviewGroup.objects.create(
            job=job,
            group_key="client:phone:0555001001",
            group_kind=ImportReviewGroup.Kind.BUNDLE_ROOT,
            status=ImportReviewGroup.Status.PENDING,
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="First group needs review.",
            entity_type="client",
            topology_side="client_side",
            root_identity={"phone": "0555001001"},
            root_label="First Group",
            root_row_ordinal=1,
            item_count=1,
            pending_item_count=1,
            blocking_item_count=0,
            suggested_group_action="update_existing",
            search_text="First Group",
            metadata={"sample_rows": [1]},
        )
        second_group = ImportReviewGroup.objects.create(
            job=job,
            group_key="client:phone:0555001002",
            group_kind=ImportReviewGroup.Kind.SINGLE_ROW,
            status=ImportReviewGroup.Status.PENDING,
            issue_group="missing_information",
            issue_title="Missing information",
            issue_summary="Second group needs review.",
            entity_type="client",
            topology_side="client_side",
            root_identity={"phone": "0555001002"},
            root_label="Second Group",
            root_row_ordinal=2,
            item_count=1,
            pending_item_count=1,
            blocking_item_count=0,
            suggested_group_action="review_ambiguous",
            search_text="Second Group",
            metadata={"sample_rows": [2]},
        )
        ImportReviewItem.objects.create(
            job=job,
            group=first_group,
            row_ordinal=1,
            entity_type="client",
            topology_side="client_side",
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="First group item.",
            raw_data={"family_name": "First Group", "phone": "0555001001"},
            normalized_data={"family_name": "First Group", "phone": "0555001001"},
        )
        ImportReviewItem.objects.create(
            job=job,
            group=second_group,
            row_ordinal=2,
            entity_type="client",
            topology_side="client_side",
            issue_group="missing_information",
            issue_title="Missing information",
            issue_summary="Second group item.",
            raw_data={"family_name": "Second Group", "phone": "0555001002"},
            normalized_data={"family_name": "Second Group", "phone": "0555001002"},
        )

        request = APIRequestFactory().get(
            f"/api/v1/import/{job.id}/review/?group_key=missing-group"
        )
        force_authenticate(request, user=user)

        response = import_review(request, str(job.id))

        assert response.status_code == 200
        assert response.data["review_filters"]["group_key"] == "client:phone:0555001001"
        assert response.data["review_rows"][0]["group_key"] == "client:phone:0555001001"
        assert response.data["review_items"][0]["group_key"] == "client:phone:0555001001"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_submit_returns_structured_duplicate_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRC")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review.csv",
            file_type="csv",
            source_path="fixture://review",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            review_rows=[
                {
                    "row": 14,
                    "entity_type": "client",
                    "data": {"family_name": "Yacine", "phone": "0555001001"},
                    "original": {"family_name": "Yacine", "phone": "0555001001"},
                }
            ],
        )

        def _raise_conflict(_self: object, **_kwargs: object) -> dict[str, object]:
            raise ImportReviewSubmitConflictError(
                detail="A few lines still need your attention.",
                row_conflicts=[
                    {
                        "row": 14,
                        "conflict_type": "duplicate_phone",
                        "field": "phone",
                        "existing_id": 2,
                        "existing_summary": "Existing Client (0555001001)",
                        "suggested_action": "use_existing_record",
                    }
                ],
                conflict_groups=[],
                conflict_item_ids=[],
            )

        monkeypatch.setattr(
            "server.api.views_import_review.ImportService.submit_review",
            _raise_conflict,
        )

        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "corrections": {},
                "decisions": {"14": {"action": "create_new"}},
                "bulk_operations": [],
                "skip_rows": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_review_submit(request, str(job.id))

        assert response.status_code == 409
        assert response.data["code"] == "IMPORT_REVIEW_DUPLICATE_CONFLICT"
        assert response.data["row_conflicts"][0]["row"] == 14
        assert response.data["row_conflicts"][0]["conflict_type"] == "duplicate_phone"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_submit_returns_structured_duplicate_conflict_from_batch_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRB")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-batch.csv",
            file_type="csv",
            source_path="fixture://review-batch",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            review_rows=[
                {
                    "row": 14,
                    "entity_type": "client",
                    "data": {"family_name": "Yacine", "phone": "0555001001"},
                    "original": {"family_name": "Yacine", "phone": "0555001001"},
                },
                {
                    "row": 15,
                    "entity_type": "client",
                    "data": {"family_name": "Yacine", "phone": "0555001001"},
                    "original": {"family_name": "Yacine", "phone": "0555001001"},
                },
            ],
        )

        def _raise_conflict_for_batch(
            _self: object,
            **_kwargs: object,
        ) -> dict[str, object]:
            raise ImportReviewSubmitConflictError(
                detail="A few lines still need your attention.",
                row_conflicts=[
                    {
                        "row": 14,
                        "conflict_type": "duplicate_phone",
                        "field": "phone",
                        "existing_id": None,
                        "existing_summary": "duplicate key value violates unique constraint",
                        "suggested_action": "review",
                    },
                    {
                        "row": 15,
                        "conflict_type": "duplicate_phone",
                        "field": "phone",
                        "existing_id": None,
                        "existing_summary": "duplicate key value violates unique constraint",
                        "suggested_action": "review",
                    },
                ],
                conflict_groups=[],
                conflict_item_ids=[],
            )

        monkeypatch.setattr(
            "server.api.views_import_review.ImportService.submit_review",
            _raise_conflict_for_batch,
        )

        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "corrections": {},
                "decisions": {
                    "14": {"action": "create_new"},
                    "15": {"action": "create_new"},
                },
                "bulk_operations": [],
                "skip_rows": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_review_submit(request, str(job.id))

        assert response.status_code == 409
        assert response.data["code"] == "IMPORT_REVIEW_DUPLICATE_CONFLICT"
        assert {int(item["row"]) for item in response.data["row_conflicts"]} == {14, 15}
        assert all(
            str(item["conflict_type"]) == "duplicate_phone"
            for item in response.data["row_conflicts"]
        )
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_submit_task_requires_agency_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_load(_user_id: int) -> object:
        raise AssertionError("load_import_user should not run when agency_id is missing")

    monkeypatch.setattr(tasks_import_review_module, "load_import_user", _unexpected_load)

    with pytest.raises(
        ValueError,
        match="import_review_submit_task: agency_id is required",
    ):
        tasks_import_review_module.import_review_submit_task.run(
            session_id="review-submit-task-missing-agency",
            user_id=77,
            agency_id=None,
            schema="tenant_77",
            correlation_id="corr-77",
        )


def test_import_review_submit_task_uses_validated_agency_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _load_user(user_id: int) -> object:
        captured["loaded_user_id"] = user_id
        return SimpleNamespace(id=user_id, role="manager", is_owner=False)

    class _TaskContext:
        def __init__(self, schema: str | None, agency_id: int, **kwargs: object) -> None:
            captured["task_context"] = {
                "schema": schema,
                "agency_id": agency_id,
                **kwargs,
            }

        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    def _run_review_submit_task(**kwargs: object) -> dict[str, object]:
        captured["run_kwargs"] = dict(kwargs)
        return {"status": "ok", "session_id": kwargs["session_id"]}

    monkeypatch.setattr(tasks_import_review_module, "load_import_user", _load_user)
    monkeypatch.setattr(tasks_import_review_module, "task_context", _TaskContext)
    monkeypatch.setattr(
        tasks_import_review_module,
        "run_review_submit_task",
        _run_review_submit_task,
    )

    result = tasks_import_review_module.import_review_submit_task.run(
        session_id="review-submit-task-valid-agency",
        user_id=88,
        agency_id=9,
        schema="tenant_9",
        correlation_id="corr-88",
    )

    assert result == {"status": "ok", "session_id": "review-submit-task-valid-agency"}
    assert captured["loaded_user_id"] == 88
    assert captured["task_context"] == {
        "schema": "tenant_9",
        "agency_id": 9,
        "actor_id": 88,
        "actor_role": "manager",
        "actor_is_owner": False,
        "correlation_id": "corr-88",
    }
    assert captured["run_kwargs"] == {
        "session_id": "review-submit-task-valid-agency",
        "actor_user_id": 88,
        "agency_id": 9,
        "correlation_id": "corr-88",
        "task_id": "",
    }


def test_import_review_submit_keeps_same_row_bundle_item_decisions_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRSAME")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-same-row.csv",
            file_type="csv",
            source_path="fixture://review-same-row",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone", "action", "type"]),
            column_mapping={
                "family_name": "family_name",
                "phone": "phone",
                "action": "action",
                "type": "type",
            },
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                    "detected_entity": "client",
                }
            },
        )
        group = ImportReviewGroup.objects.create(
            job=job,
            group_key="client:phone:0555001001",
            group_kind=ImportReviewGroup.Kind.BUNDLE_ROOT,
            status=ImportReviewGroup.Status.PENDING,
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This root needs review.",
            entity_type="client",
            topology_side="client_side",
            root_identity={"phone": "0555001001"},
            root_label="Yacine",
            root_row_ordinal=1,
            item_count=2,
            pending_item_count=2,
            blocking_item_count=0,
            suggested_group_action="review_ambiguous",
            search_text="yacine 0555001001 1",
        )
        client_item = ImportReviewItem.objects.create(
            job=job,
            group=group,
            row_ordinal=1,
            entity_type="client",
            topology_side="client_side",
            issue_group="possible_duplicate",
            issue_title="Possible duplicate",
            issue_summary="This looks very close to an existing record.",
            suggested_action="update_existing",
            suggested_existing_id=42,
            suggested_confidence=0.9,
            raw_data={"family_name": "Yacine", "phone": "0555001001"},
            normalized_data={"family_name": "Yacine", "phone": "0555001001"},
            candidate_matches=[{"id": 42, "row_version": 3}],
        )
        demande_item = ImportReviewItem.objects.create(
            job=job,
            group=group,
            row_ordinal=1,
            entity_type="demande",
            topology_side="client_side",
            issue_group="missing_information",
            issue_title="Missing information",
            issue_summary="A few important details are missing or unclear.",
            suggested_action="create_new",
            raw_data={"action": "buy", "type": "apartment"},
            normalized_data={"action": "buy", "type": "apartment"},
        )

        captured: dict[str, object] = {}

        def _capture_actions(**kwargs: object) -> ReviewResolutionState:
            inputs = kwargs["inputs"]
            captured["decisions"] = dict(inputs.decisions_map)
            captured["corrections"] = dict(inputs.corrections_map)
            captured["skip_rows"] = set(inputs.skip_rows_set)
            return ReviewResolutionState()

        monkeypatch.setattr(
            "server.services.import_review_submit_service.collect_review_actions",
            _capture_actions,
        )

        def _enqueue_review_submit(_task: object, **kwargs: object) -> object:
            captured["enqueue_kwargs"] = dict(kwargs)
            return SimpleNamespace(id=str(kwargs.get("task_id", "")))

        monkeypatch.setattr(
            "server.api.views_import_review.enqueue_import_task",
            _enqueue_review_submit,
        )
        monkeypatch.setattr(
            "server.api.views_import_review.register_task", lambda *args, **kwargs: None
        )

        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "item_decisions": {
                    str(client_item.id): {
                        "action": "update_existing",
                        "entity_type": "client",
                        "existing_id": 42,
                        "row_version": 3,
                        "corrections": {
                            "family_name": "Yacine Edited",
                        },
                    },
                    str(demande_item.id): {
                        "action": "create_new",
                        "entity_type": "demande",
                    },
                },
                "group_decisions": {},
                "bulk_operations": [],
                "skip_item_ids": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_review_submit(request, str(job.id))
        job.refresh_from_db()
        dispatch = dict(workflow_payload(job).get("review_submit_dispatch", {}) or {})

        assert response.status_code == 202
        assert set(dict(captured.get("decisions", {}) or {}).keys()) == {
            "1:client",
            "1:demande",
        }
        assert dict(captured.get("corrections", {}) or {}) == {
            "1:client": {
                "family_name": "Yacine Edited",
            }
        }
        assert list(captured.get("skip_rows", []) or []) == []
        assert str(response.data["task_id"]) == str(job.task_id or "")
        assert captured["enqueue_kwargs"]["task_id"] == response.data["task_id"]
        assert dispatch["task_id"] == response.data["task_id"]
        assert dispatch["status"] == "published"
        assert dict(workflow_payload(job).get("review_submit", {}) or {}).get("corrections") == {
            "1:client": {
                "family_name": "Yacine Edited",
            }
        }
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_submit_publish_failure_leaves_truthful_dispatch_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRPUBF")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-publish-failure.csv",
            file_type="csv",
            source_path="fixture://review-publish-failure",
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
            lambda _task, **_kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
        )
        register_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(
            "server.api.views_import_review.register_task",
            lambda *args, **kwargs: register_calls.append((args, dict(kwargs))),
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
        job.refresh_from_db()
        workflow = workflow_payload(job)
        dispatch = dict(workflow.get("review_submit_dispatch", {}) or {})

        assert response.status_code == 202
        assert job.status == ImportJob.Status.RUNNING
        assert job.stage == ImportJob.Stage.REVIEW
        assert str(job.task_id or "") == str(response.data["task_id"] or "")
        assert dispatch["task_id"] == response.data["task_id"]
        assert dispatch["status"] == "publish_failed"
        assert dispatch["last_error_code"] == "review_submit_publish_failed"
        assert "review_submit" in workflow
        assert dict(job.result_summary or {}).get("review_submit_error") is None
        assert register_calls == []
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_submit_does_not_complete_when_review_overflow_is_still_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPROFLOW")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-overflow-submit.csv",
            file_type="csv",
            source_path="fixture://review-overflow-submit",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            progress_detail={"phase": "review", "review_overflow_count": 2},
            result_summary={
                "row_count": 1,
                "review_overflow_count": 2,
                "error_count": 1,
                "errors": [
                    {
                        "row": 0,
                        "errors": [
                            "2 additional rows required review but exceeded the review cap."
                        ],
                    }
                ],
            },
            review_rows=[
                {
                    "row": 14,
                    "entity_type": "client",
                    "data": {"family_name": "Overflow Client", "phone": "0555001001"},
                    "original": {"family_name": "Overflow Client", "phone": "0555001001"},
                }
            ],
        )

        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "corrections": {},
                "decisions": {"14": {"action": "skip"}},
                "bulk_operations": [],
                "skip_rows": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_review_submit(request, str(job.id))
        job.refresh_from_db()

        assert response.status_code == 409
        assert response.data["code"] == "IMPORT_REVIEW_CAPACITY_EXCEEDED"
        assert response.data["review_state"] == "emergency_overflow"
        assert response.data["overflow_blocking"] is True
        assert response.data["review_disabled"] is True
        assert "safely process" in str(response.data["review_disabled_reason"] or "").lower()
        assert job.status == ImportJob.Status.READY
        assert job.stage == ImportJob.Stage.REVIEW
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_submit_returns_capacity_exceeded_for_overflow_only_job() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPROWO")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="overflow-only.csv",
            file_type="csv",
            source_path="fixture://overflow-only",
            status=ImportJob.Status.FAILED,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            progress_detail={"phase": "review", "review_overflow_count": 2},
            result_summary={
                "row_count": 0,
                "review_overflow_count": 2,
                "review_state": "emergency_overflow",
                "overflow_blocking": True,
            },
            review_rows=[],
        )

        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "corrections": {},
                "decisions": {},
                "bulk_operations": [],
                "skip_rows": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_review_submit(request, str(job.id))

        assert response.status_code == 409
        assert response.data["code"] == "IMPORT_REVIEW_CAPACITY_EXCEEDED"
        assert response.data["overflow_blocking"] is True
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_submit_does_not_count_same_plain_row_errors_as_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRTRM")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review-terminal.csv",
            file_type="csv",
            source_path="fixture://review-terminal",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            detected_columns=_detected_columns(["family_name", "phone"]),
            column_mapping={"family_name": "family_name", "phone": "phone"},
            review_rows=[
                {
                    "row": 14,
                    "entity_type": "client",
                    "data": {"family_name": "Terminal", "phone": "0555003333"},
                    "original": {"family_name": "Terminal", "phone": "0555003333"},
                }
            ],
        )

        def _fake_apply_review_resolutions(**_kwargs: object) -> dict[str, object]:
            return {
                "created_count": 0,
                "created_entity_counts": {},
                "updated_count": 0,
                "still_review": [
                    {
                        "row": 14,
                        "data": {"family_name": "Terminal", "phone": "0555003333"},
                        "original": {"family_name": "Terminal", "phone": "0555003333"},
                    }
                ],
                "errors": [{"row": 14, "entity_type": "", "errors": ["still unresolved"]}],
                "audit_entries": [],
                "decision_summary": {
                    "create_new": 0,
                    "update_existing": 0,
                    "review_ambiguous": 1,
                    "skip": 0,
                },
                "learning_summary": {},
                "dead_letter_summary": {},
            }

        monkeypatch.setattr(
            "server.api.views_import_review.enqueue_import_task",
            lambda _task, **_kwargs: SimpleNamespace(id="review-submit-task-terminal"),
        )
        monkeypatch.setattr(
            "server.api.views_import_review.register_task", lambda *args, **kwargs: None
        )
        monkeypatch.setattr(
            "server.services.import_review_execution_service.apply_review_resolutions",
            _fake_apply_review_resolutions,
        )

        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "corrections": {},
                "decisions": {"14": {"action": "review_ambiguous"}},
                "bulk_operations": [],
                "skip_rows": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_review_submit(request, str(job.id))
        job.refresh_from_db()

        assert response.status_code == 202
        run_review_submit_task(
            session_id=str(job.id),
            actor_user_id=user_id,
            agency_id=agency_id,
            correlation_id="",
        )
        job.refresh_from_db()

        assert int((job.result_summary or {}).get("error_count", 0) or 0) == 0
        assert int((job.result_summary or {}).get("review_count", 0) or 0) == 1
        assert job.status == ImportJob.Status.READY
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_review_defaults_disabled_reason_for_overflow() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPROR")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="overflow-reason.csv",
            file_type="csv",
            source_path="fixture://overflow-reason",
            status=ImportJob.Status.FAILED,
            stage=ImportJob.Stage.REVIEW,
            detected_entity="client",
            progress_detail={"phase": "review", "review_overflow_count": 1},
            result_summary={
                "row_count": 1,
                "review_overflow_count": 1,
                "review_state": "emergency_overflow",
                "overflow_blocking": True,
            },
            review_rows=[],
        )

        request = APIRequestFactory().get(f"/api/v1/import/{job.id}/review/")
        force_authenticate(request, user=user)

        response = import_review(request, str(job.id))

        assert response.status_code == 200
        assert response.data["review_disabled"] is True
        assert "safely process" in str(response.data["review_disabled_reason"] or "").lower()
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_presign_returns_account_scope_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPRS")
    try:
        monkeypatch.setattr(
            "server.api.views_import_upload.generate_presigned_upload",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("agency_id is required for storage.")
            ),
        )

        request = APIRequestFactory().post(
            "/api/v1/import/presign/",
            {
                "filename": "clients.csv",
                "content_type": "text/csv",
                "size_bytes": 12,
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_presign(request)

        assert response.status_code == 403
        assert response.data["code"] == "IMPORT_ACCOUNT_SCOPE_REQUIRED"
        assert "not ready for imports" in response.data["detail"].lower()
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_import_presign_returns_retryable_storage_readiness_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSR")
    try:
        monkeypatch.setattr(
            "server.api.views_import_upload.generate_presigned_upload",
            lambda **_kwargs: (_ for _ in ()).throw(
                StorageNotReadyError(
                    "storage warming up",
                    code="IMPORT_STORAGE_NOT_READY",
                    retry_after_ms=1750,
                )
            ),
        )

        request = APIRequestFactory().post(
            "/api/v1/import/presign/",
            {
                "filename": "clients.csv",
                "content_type": "text/csv",
                "size_bytes": 12,
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_presign(request)

        assert response.status_code == 503
        assert response.data["code"] == "IMPORT_STORAGE_NOT_READY"
        assert response.data["retryable"] is True
        assert response.data["retry_after_ms"] == 1750
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)
