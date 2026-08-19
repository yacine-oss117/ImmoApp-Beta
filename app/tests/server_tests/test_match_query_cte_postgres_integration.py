from __future__ import annotations

import uuid

import pytest

pytest.importorskip(
    "psycopg",
    reason="matcher integration tests require server dependencies",
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
from core.matcher.match_query_cte import build_match_cte
from server.pg.schema import ensure_schema
from server.pg.uow import get_uow, use_security_context


def test_match_query_cte_handles_location_and_wilaya_fallback_paths() -> None:
    ensure_django()
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone_suffix = str(int(suffix, 16))[-6:].rjust(6, "0")

    agency_id = 0
    client_id = 0
    listing_id = 0
    demande_loc_id = 0
    demande_wilaya_id = 0
    offer_match_id = 0
    offer_filtered_id = 0

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"MQC{suffix}", f"Match CTE Agency {suffix}")
        conn.commit()

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                client_id = client_write.upsert_client(
                    session,
                    {
                        "family_name": f"Matcher Client {suffix}",
                        "phone": f"0555{phone_suffix}",
                        "status": "active",
                    },
                )
                listing_id = listing_write.upsert_listing(
                    session,
                    {
                        "family_name": f"Matcher Listing {suffix}",
                        "phone": f"0666{phone_suffix}",
                        "status": "available",
                    },
                )
                demande_loc_id = demande_write.create_demande(
                    session,
                    {
                        "client_id": client_id,
                        "type": "apartment",
                        "type_id": 1,
                        "action": "buy",
                        "action_id": 1,
                        "wilaya": "Alger",
                        "wilaya_id": 16,
                        "locations": f"Hydra {suffix}",
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
                )
                demande_wilaya_id = demande_write.create_demande(
                    session,
                    {
                        "client_id": client_id,
                        "type": "apartment",
                        "type_id": 1,
                        "action": "buy",
                        "action_id": 1,
                        "wilaya": "Alger",
                        "wilaya_id": 16,
                        "locations": "",
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
                )
                offer_match_id = offer_write.create_offer(
                    session,
                    listing_id,
                    {
                        "type": "apartment",
                        "type_id": 1,
                        "action": "sell",
                        "action_id": 3,
                        "status": "available",
                        "wilaya": "Alger",
                        "wilaya_id": 16,
                        "location": f"Hydra {suffix}",
                        "beds": 3,
                        "surface": 90,
                        "budget": 200,
                        "floor": 2,
                        "elevator": True,
                        "accessibility_supported": True,
                    },
                )
                offer_filtered_id = offer_write.create_offer(
                    session,
                    listing_id,
                    {
                        "type": "house",
                        "type_id": 2,
                        "action": "sell",
                        "action_id": 3,
                        "status": "available",
                        "wilaya": "Alger",
                        "wilaya_id": 16,
                        "location": f"Hydra {suffix}",
                        "beds": 3,
                        "surface": 90,
                        "budget": 200,
                        "floor": 2,
                        "elevator": True,
                        "accessibility_supported": True,
                    },
                )

            with get_uow().session() as session:
                loc_query = build_match_cte(
                    demande_ids=[demande_loc_id],
                    select_cols="d.id AS demande_id, o.id AS offer_id",
                )
                loc_rows = session.execute(
                    loc_query.sql + " SELECT * FROM matched_pairs",
                    loc_query.params,
                ).fetchall()

                wilaya_query = build_match_cte(
                    demande_ids=[demande_wilaya_id],
                    select_cols="d.id AS demande_id, o.id AS offer_id",
                )
                wilaya_rows = session.execute(
                    wilaya_query.sql + " SELECT * FROM matched_pairs",
                    wilaya_query.params,
                ).fetchall()

        loc_offer_ids = {int(row["offer_id"]) for row in loc_rows}
        wilaya_offer_ids = {int(row["offer_id"]) for row in wilaya_rows}

        assert offer_match_id in loc_offer_ids
        assert offer_filtered_id not in loc_offer_ids
        assert offer_match_id in wilaya_offer_ids
        assert offer_filtered_id not in wilaya_offer_ids
    finally:
        conn.rollback()
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id)
