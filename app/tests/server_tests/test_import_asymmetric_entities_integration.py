from __future__ import annotations

import csv
import uuid
from pathlib import Path

import pytest

pytest.importorskip("psycopg", reason="import integration tests require Postgres")

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from core.data import client_repo_write, listing_repo_write  # noqa: E402
from core.importer.detection.column_detector import ColumnDetector  # noqa: E402
from server.imports.models import ImportJob  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import get_uow, use_security_context  # noqa: E402
from server.services import import_executor  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _render_fixture(template_name: str, replacements: dict[str, str], out_path: Path) -> Path:
    text = (FIXTURES_DIR / template_name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def _headers(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        first = next(reader, [])
    return [str(h).strip() for h in first if str(h).strip()]


def _write_combined_bundle_csv(*, path: Path, root_entity: str) -> Path:
    if root_entity == "client":
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
        rows = [
            [
                "Bundle A",
                "0555008101",
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
            ],
            [
                "Bundle A",
                "0555008101",
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
            ],
            [
                "Bundle B",
                "0555008102",
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
            ],
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
            "remarks",
        ]
        rows = [
            [
                "Owner A",
                "0666008101",
                "available",
                "sell",
                "apartment",
                "16",
                "Ben Aknoun",
                "15000000",
                "110",
                "3",
                "2",
                "OFF_A1",
            ],
            [
                "Owner A",
                "0666008101",
                "available",
                "sell",
                "apartment",
                "16",
                "Hydra",
                "18000000",
                "125",
                "3",
                "4",
                "OFF_A2",
            ],
            [
                "Owner B",
                "0666008102",
                "available",
                "sell",
                "villa",
                "16",
                "Cheraga",
                "32000000",
                "260",
                "5",
                "1",
                "OFF_B1",
            ],
        ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _detected_columns(headers: list[str]) -> list[dict[str, object]]:
    detector = ColumnDetector()
    result: list[dict[str, object]] = []
    for idx, header in enumerate(headers):
        det = detector.detect_column_type(header, sample_values=[])
        result.append(
            {
                "index": idx,
                "header": header,
                "detected_type": det.detected_type,
                "confidence": det.confidence,
                "sample_values": [],
            }
        )
    return result


def _seed_owner_rows(*, agency_id: int, suffix: str) -> tuple[int, int]:
    digits = "".join(ch for ch in suffix if ch.isdigit())
    digits = (digits + "0123456789")[:6]
    with use_security_context(agency_id=agency_id, is_superuser=False):
        with get_uow().transaction(actor="test_import_seed") as session:
            client_id = client_repo_write.upsert_client(
                session,
                {
                    "family_name": f"Import Client {suffix}",
                    "phone": f"0556{digits}",
                    "status": "active",
                },
            )
            listing_id = listing_repo_write.upsert_listing(
                session,
                {
                    "family_name": f"Import Listing {suffix}",
                    "phone": f"0667{digits}",
                    "status": "available",
                },
            )
    return int(client_id), int(listing_id)


def _make_job(
    *,
    user_id: int,
    agency_id: int,
    entity_type: str,
    csv_path: Path,
) -> ImportJob:
    headers = _headers(csv_path)
    mapping = {header: header for header in headers}
    return ImportJob.objects.create(
        user_id=user_id,
        agency_id=agency_id,
        filename=csv_path.name,
        file_type="csv",
        source_path="fixture://import",
        status=ImportJob.Status.READY,
        stage=ImportJob.Stage.EXECUTION,
        detected_entity=entity_type,
        detected_columns=_detected_columns(headers),
        column_mapping=mapping,
        result_summary={"row_count": 3},
    )


def _run_import_job(
    *,
    monkeypatch: pytest.MonkeyPatch,
    csv_path: Path,
    job: ImportJob,
    agency_id: int,
    user_id: int,
) -> import_executor.ImportResult:
    monkeypatch.setattr(
        import_executor, "download_to_temp", lambda _source_path, suffix=None: csv_path
    )

    import server.api.notifications as notifications

    monkeypatch.setattr(notifications, "notify_only", lambda **_kwargs: None)
    monkeypatch.setattr(notifications, "record_and_notify", lambda **_kwargs: None)

    with use_security_context(agency_id=agency_id, is_superuser=False):
        return import_executor.execute_import(job=job, user_id=user_id)


def test_import_demande_child_only_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]

    agency_id = 0
    user_id = 0
    client_id = 0
    listing_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IMPDA{suffix}", f"Import Demande {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"imp_dem_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        client_id, listing_id = _seed_owner_rows(agency_id=agency_id, suffix=suffix)

        csv_path = _render_fixture(
            "import_messy_demandes.csv",
            {"__CLIENT_ID__": str(client_id)},
            tmp_path / f"demandes_{suffix}.csv",
        )
        job = _make_job(
            user_id=user_id,
            agency_id=agency_id,
            entity_type="demande",
            csv_path=csv_path,
        )

        result = _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_id,
            user_id=user_id,
        )
        assert result.success is False
        assert result.error_count == 1
        assert (
            "requests-only files aren't supported" in " ".join(result.errors[0]["errors"]).lower()
        )

        inserted = conn.execute(
            "SELECT COUNT(*) AS c FROM demandes WHERE client_id = %s",
            (client_id,),
        ).fetchone()
        assert inserted is not None
        assert int(inserted["c"]) == 0
    finally:
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def test_import_offer_child_only_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]

    agency_id = 0
    user_id = 0
    client_id = 0
    listing_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IMPOF{suffix}", f"Import Offer {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"imp_off_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        client_id, listing_id = _seed_owner_rows(agency_id=agency_id, suffix=suffix)

        csv_path = _render_fixture(
            "import_messy_offers.csv",
            {"__LISTING_ID__": str(listing_id)},
            tmp_path / f"offers_{suffix}.csv",
        )
        job = _make_job(
            user_id=user_id,
            agency_id=agency_id,
            entity_type="offer",
            csv_path=csv_path,
        )

        result = _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_id,
            user_id=user_id,
        )
        assert result.success is False
        assert result.error_count == 1
        assert "offers-only files aren't supported" in " ".join(result.errors[0]["errors"]).lower()

        inserted = conn.execute(
            "SELECT COUNT(*) AS c FROM offers WHERE listing_id = %s",
            (listing_id,),
        ).fetchone()
        assert inserted is not None
        assert int(inserted["c"]) == 0
    finally:
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


@pytest.mark.parametrize(
    ("root_entity", "topology_side", "root_table", "child_table", "child_column", "child_prefix"),
    [
        ("client", "client_side", "clients", "demandes", "remarks", "DEM_"),
        ("listing", "listing_side", "listings", "offers", "remarks", "OFF_"),
    ],
)
def test_import_same_side_bundle_accepts_combined_rows_without_separate_root_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_entity: str,
    topology_side: str,
    root_table: str,
    child_table: str,
    child_column: str,
    child_prefix: str,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]

    agency_id = 0
    user_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IMPCB{suffix}", f"Import Combined {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"imp_combined_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        csv_path = _write_combined_bundle_csv(
            path=tmp_path / f"combined_{root_entity}_{suffix}.csv",
            root_entity=root_entity,
        )
        headers = _headers(csv_path)
        mapping = {header: header for header in headers}
        job = ImportJob.objects.create(
            user_id=user_id,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://combined-bundle",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity=root_entity,
            detected_columns=_detected_columns(headers),
            column_mapping=mapping,
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": topology_side,
                    "detected_entity": root_entity,
                }
            },
            result_summary={"row_count": 3},
        )

        result = _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_id,
            user_id=user_id,
        )

        assert result.success is True
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session(actor="test_import_combined_bundle_verify") as session:
                root_row = session.execute(
                    f"SELECT COUNT(*) AS c FROM {root_table} WHERE agency_id = %s AND deleted_at IS NULL",
                    (agency_id,),
                ).fetchone()
                child_row = session.execute(
                    f"SELECT COUNT(*) AS c FROM {child_table} "
                    f"WHERE agency_id = %s AND deleted_at IS NULL AND {child_column} LIKE %s",
                    (agency_id, f"{child_prefix}%"),
                ).fetchone()
        assert root_row is not None and int(root_row["c"]) == 2
        assert child_row is not None and int(child_row["c"]) == 3
    finally:
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)
