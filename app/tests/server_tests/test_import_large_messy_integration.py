from __future__ import annotations

import csv
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("psycopg", reason="import integration tests require Postgres")

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from core.importer.detection.column_detector import ColumnDetector  # noqa: E402
from server.imports.models import ImportJob  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import use_security_context  # noqa: E402
from server.services import import_executor  # noqa: E402


def _write_large_messy_csv(
    *,
    path: Path,
    entity_type: str,
    row_count: int,
) -> Path:
    if entity_type == "demande":
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
            "floor_min",
            "floor_max",
            "furnished",
            "elevator",
            "accessibility_required",
            "remarks",
        ]
    else:
        headers = [
            "family_name",
            "phone",
            "status",
            "action",
            "type",
            "wilaya",
            "location",
            "budget",
            "surface",
            "beds",
            "floor",
            "furnished",
            "elevator",
            "accessibility_supported",
            "remarks",
        ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for idx in range(row_count):
            root_group = idx % 18
            group_token = chr(65 + root_group)
            if entity_type == "demande":
                budget_min = "1200000"
                budget_max = "2400000"
                location = "Hydra"
                remark = f"DEM_LARGE_OK_{idx}"
                if idx % 17 == 0:
                    budget_min = ""
                    remark = f"DEM_LARGE_REVIEW_RANGE_{idx}"
                elif idx % 29 == 0:
                    location = "Unknown\u2011Sector\u2011XYZ"
                    remark = f"DEM_LARGE_REVIEW_LOC_{idx}"
                writer.writerow(
                    [
                        f"Large Client {group_token}",
                        f"0556{root_group:06d}",
                        "active",
                        "buy",
                        "apartment",
                        16,
                        location,
                        budget_min,
                        budget_max,
                        60,
                        130,
                        2,
                        0,
                        6,
                        "any",
                        "yes",
                        "no",
                        remark,
                    ]
                )
            else:
                budget = "15000000"
                location = "Ben Aknoun"
                remark = f"OFF_LARGE_OK_{idx}"
                if idx % 17 == 0:
                    budget = ""
                    remark = f"OFF_LARGE_REVIEW_BUDGET_{idx}"
                elif idx % 29 == 0:
                    location = "Unknown\u2011District\u2011XYZ"
                    remark = f"OFF_LARGE_REVIEW_LOC_{idx}"
                writer.writerow(
                    [
                        f"Large Listing {group_token}",
                        f"0667{root_group:06d}",
                        "available",
                        "sell",
                        "apartment",
                        16,
                        location,
                        budget,
                        110,
                        3,
                        2,
                        "no",
                        "yes",
                        "no",
                        remark,
                    ]
                )

    return path


def _detected_columns(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        headers = next(csv.reader(handle), [])
    detector = ColumnDetector()
    detected: list[dict[str, object]] = []
    for idx, header in enumerate(headers):
        result = detector.detect_column_type(str(header), sample_values=[])
        detected.append(
            {
                "index": idx,
                "header": str(header),
                "detected_type": result.detected_type,
                "confidence": result.confidence,
                "sample_values": [],
            }
        )
    return detected


def _run_import_job(
    *,
    monkeypatch: pytest.MonkeyPatch,
    csv_path: Path,
    job: ImportJob,
    agency_id: int,
    user_id: int,
) -> import_executor.ImportResult:
    monkeypatch.setattr(
        import_executor,
        "download_to_temp",
        lambda _source_path, suffix=None: csv_path,
    )

    import server.api.notifications as notifications

    monkeypatch.setattr(notifications, "notify_only", lambda **_kwargs: None)
    monkeypatch.setattr(notifications, "record_and_notify", lambda **_kwargs: None)

    with use_security_context(agency_id=agency_id, is_superuser=False):
        return import_executor.execute_import(job=job, user_id=user_id)


@pytest.mark.parametrize(
    ("entity_type", "row_count", "time_budget_s"),
    (
        ("demande", 240, 25.0),
        ("offer", 240, 25.0),
    ),
)
def test_large_messy_import_routes_review_and_persists_valid_rows(
    *,
    entity_type: str,
    row_count: int,
    time_budget_s: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]

    agency_id = 0
    user_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IMPLG{suffix}", f"Import Large {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"imp_lg_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        csv_path = _write_large_messy_csv(
            path=tmp_path / f"{entity_type}_large_{suffix}.csv",
            entity_type=entity_type,
            row_count=row_count,
        )

        headers = [item.get("header") for item in _detected_columns(csv_path)]
        mapping = {str(header): str(header) for header in headers if header}
        root_entity = "client" if entity_type == "demande" else "listing"
        topology_side = "client_side" if entity_type == "demande" else "listing_side"
        job = ImportJob.objects.create(
            user_id=user_id,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://import-large",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity=root_entity,
            detected_columns=_detected_columns(csv_path),
            column_mapping=mapping,
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": topology_side,
                    "detected_entity": root_entity,
                }
            },
            result_summary={"row_count": row_count},
        )

        started = time.perf_counter()
        result = _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_id,
            user_id=user_id,
        )
        elapsed_s = time.perf_counter() - started

        job.refresh_from_db()

        assert result.success is True
        assert result.created_count > 0
        assert result.created_count <= row_count + 18
        assert job.stage == ImportJob.Stage.REVIEW
        assert len(job.review_rows or []) > 0
        assert elapsed_s <= time_budget_s

        if entity_type == "demande":
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM demandes WHERE agency_id = %s AND remarks LIKE %s",
                (agency_id, "DEM_LARGE_OK_%"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM offers WHERE agency_id = %s AND remarks LIKE %s",
                (agency_id, "OFF_LARGE_OK_%"),
            ).fetchone()
        assert row is not None
        assert int(row["c"]) > 0
    finally:
        if agency_id:
            conn.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importrowaudit WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
        if agency_id:
            conn.execute("DELETE FROM offers WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM listings WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        if user_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_id,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        if agency_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()
