from __future__ import annotations

import uuid

import pytest

pytest.importorskip(
    "psycopg",
    reason="child batch write integration tests require server dependencies",
)
pytest.importorskip(
    "cryptography",
    reason="child batch write integration tests require full server dependencies",
)

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    ensure_django,
)
from core.data import client_repo_write as client_write
from core.data import demande_repo_write as demande_write
from core.data import listing_repo_write as listing_write
from core.data import offer_repo_write as offer_write
from server.pg.schema import ensure_schema
from server.pg.uow import get_uow, use_security_context


def _create_agency(prefix: str) -> int:
    ensure_django()
    ensure_schema()
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"{prefix}{uuid.uuid4().hex[:6]}", f"{prefix} Agency")
        conn.commit()
        return agency_id
    finally:
        conn.close()


def _cleanup_agency(agency_id: int) -> None:
    cleanup_import_test_agency(agency_id=agency_id)


def test_insert_demandes_batch_creates_rows_and_location_links() -> None:
    agency_id = _create_agency("IBDWDEM")
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                client_id = client_write.upsert_client(
                    session,
                    {
                        "family_name": "Batch Demande Client",
                        "phone": f"0556{uuid.uuid4().hex[:6]}",
                        "status": "active",
                    },
                )
                demande_ids = demande_write.insert_demandes_batch(
                    session,
                    [
                        {
                            "client_id": client_id,
                            "type": "apartment",
                            "type_id": 1,
                            "action": "buy",
                            "action_id": 1,
                            "wilaya": "Alger",
                            "wilaya_id": 16,
                            "locations": "Hydra; El Biar",
                            "beds_min": 2,
                            "surface_min": 60,
                            "surface_max": 120,
                            "budget_min": 100,
                            "budget_max": 300,
                            "floor_min": 0,
                            "floor_max": 8,
                            "elevator": True,
                            "accessibility_required": True,
                        },
                        {
                            "client_id": client_id,
                            "type": "apartment",
                            "type_id": 1,
                            "action": "buy",
                            "action_id": 1,
                            "wilaya": "Alger",
                            "wilaya_id": 16,
                            "locations": "Hydra",
                            "beds_min": 3,
                            "surface_min": 70,
                            "surface_max": 140,
                            "budget_min": 200,
                            "budget_max": 400,
                            "floor_min": 0,
                            "floor_max": 8,
                            "elevator": True,
                            "accessibility_required": False,
                        },
                    ],
                )
                link_rows = session.execute(
                    """
                    SELECT dl.demande_id, l.location_norm
                    FROM demande_locations dl
                    JOIN locations l ON l.location_id = dl.location_id
                    WHERE dl.demande_id = ANY(%s)
                    ORDER BY dl.demande_id, l.location_norm
                    """,
                    (demande_ids,),
                ).fetchall()

        assert len(demande_ids) == 2
        assert [(int(row["demande_id"]), str(row["location_norm"])) for row in link_rows] == [
            (demande_ids[0], "el biar"),
            (demande_ids[0], "hydra"),
            (demande_ids[1], "hydra"),
        ]
    finally:
        _cleanup_agency(agency_id)


def test_insert_offers_batch_creates_rows_and_location_links() -> None:
    agency_id = _create_agency("IBDWOFF")
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                listing_id = listing_write.upsert_listing(
                    session,
                    {
                        "family_name": "Batch Offer Listing",
                        "phone": f"0666{uuid.uuid4().hex[:6]}",
                        "status": "available",
                    },
                )
                offer_ids = offer_write.insert_offers_batch(
                    session,
                    [
                        {
                            "listing_id": listing_id,
                            "type": "apartment",
                            "type_id": 1,
                            "action": "sell",
                            "action_id": 3,
                            "status": "available",
                            "wilaya": "Alger",
                            "wilaya_id": 16,
                            "location": "Ben Aknoun; Hydra",
                            "beds": 3,
                            "surface": 120,
                            "budget": 150000,
                            "floor": 2,
                            "furnished": "no",
                            "elevator": True,
                            "accessibility_supported": False,
                        },
                        {
                            "listing_id": listing_id,
                            "type": "apartment",
                            "type_id": 1,
                            "action": "sell",
                            "action_id": 3,
                            "status": "available",
                            "wilaya": "Alger",
                            "wilaya_id": 16,
                            "location": "Hydra",
                            "beds": 4,
                            "surface": 140,
                            "budget": 180000,
                            "floor": 3,
                            "furnished": "yes",
                            "elevator": True,
                            "accessibility_supported": True,
                        },
                    ],
                )
                link_rows = session.execute(
                    """
                    SELECT ol.offer_id, l.location_norm
                    FROM offer_locations ol
                    JOIN locations l ON l.location_id = ol.location_id
                    WHERE ol.offer_id = ANY(%s)
                    ORDER BY ol.offer_id, l.location_norm
                    """,
                    (offer_ids,),
                ).fetchall()

        assert len(offer_ids) == 2
        assert [(int(row["offer_id"]), str(row["location_norm"])) for row in link_rows] == [
            (offer_ids[0], "ben aknoun"),
            (offer_ids[0], "hydra"),
            (offer_ids[1], "hydra"),
        ]
    finally:
        _cleanup_agency(agency_id)
