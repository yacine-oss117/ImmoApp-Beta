from __future__ import annotations

import uuid

import psycopg
import pytest

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)
from server.pg.schema import ensure_schema


def _insert_client(conn, *, agency_id: int, suffix: str) -> int:
    row = conn.execute(
        """
        INSERT INTO clients (agency_id, family_name, phone, status, created_at, updated_at)
        VALUES (%s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (agency_id, f"Client {suffix}", f"0550{suffix[-6:].rjust(6, '0')}"),
    ).fetchone()
    return int(row["id"])


def _insert_listing(conn, *, agency_id: int, suffix: str) -> int:
    row = conn.execute(
        """
        INSERT INTO listings (agency_id, family_name, phone, status, created_at, updated_at)
        VALUES (%s, %s, %s, 'available', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (agency_id, f"Listing {suffix}", f"0660{suffix[-6:].rjust(6, '0')}"),
    ).fetchone()
    return int(row["id"])


def _insert_demande(conn, *, agency_id: int, client_id: int, suffix: str) -> int:
    row = conn.execute(
        """
        INSERT INTO demandes (
            client_id, agency_id, type, type_id, action, action_id, wilaya, wilaya_id,
            locations, beds_min, surface_min, surface_max, budget_min, budget_max,
            budget_range, surface_range, beds_range, floor_min, floor_max,
            elevator, accessibility_required, created_at, updated_at
        )
        VALUES (
            %s, %s, 'apartment', 1, 'buy', 1, 'Alger', 16,
            %s, 2, 60, 120, 100, 300,
            numrange(100::numeric, 300::numeric, '[]'),
            numrange(60::numeric, 120::numeric, '[]'),
            int4range(2, NULL, '[]'),
            0, 8, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (client_id, agency_id, f"Hydra {suffix}"),
    ).fetchone()
    return int(row["id"])


def _insert_offer(conn, *, agency_id: int, listing_id: int, suffix: str) -> int:
    row = conn.execute(
        """
        INSERT INTO offers (
            listing_id, agency_id, type, type_id, action, action_id, status,
            wilaya, wilaya_id, location, beds, surface, budget,
            floor, elevator, accessibility_supported, created_at, updated_at
        )
        VALUES (
            %s, %s, 'apartment', 1, 'sell', 3, 'available',
            'Alger', 16, %s, 3, 90, 200,
            2, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (listing_id, agency_id, f"Hydra {suffix}"),
    ).fetchone()
    return int(row["id"])


def _insert_contract(conn, *, agency_id: int, client_id: int, listing_id: int, suffix: str) -> int:
    row = conn.execute(
        """
        INSERT INTO contracts (
            client_id, listing_id, agency_id, contract_type, status,
            amount, deposit, terms, notes, created_at, updated_at
        )
        VALUES (%s, %s, %s, 'sale', 'draft', 1000, 100, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (client_id, listing_id, agency_id, f"terms-{suffix}", f"notes-{suffix}"),
    ).fetchone()
    return int(row["id"])


def _insert_location(conn, *, suffix: str) -> int:
    row = conn.execute(
        "INSERT INTO locations (location_norm) VALUES (%s) RETURNING location_id",
        (f"loc-{suffix}",),
    ).fetchone()
    return int(row["location_id"])


def _insert_storage_object(conn, *, agency_id: int, user_id: int, suffix: str) -> str:
    row = conn.execute(
        """
        INSERT INTO storage_objects (
            agency_id, user_id, role, bucket, object_key, status, created_at
        )
        VALUES (%s, %s, 'manager', 'offers', %s, 'ready', CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (agency_id, user_id, f"obj-{suffix}"),
    ).fetchone()
    return str(row["id"])


@pytest.fixture()
def tenant_fixture():
    ensure_django()
    ensure_schema()
    conn = admin_conn()
    suffix = uuid.uuid4().hex[:10]
    try:
        agency_a = create_agency(conn, f"THA{suffix}", f"Tenant Hardening A {suffix}")
        agency_b = create_agency(conn, f"THB{suffix}", f"Tenant Hardening B {suffix}")
        user_a = create_manager_user(
            conn,
            agency_id=agency_a,
            username=f"mgr_a_{suffix}",
            password="TenantHardening123!",
        )
        user_b = create_manager_user(
            conn,
            agency_id=agency_b,
            username=f"mgr_b_{suffix}",
            password="TenantHardening123!",
        )
        client_a = _insert_client(conn, agency_id=agency_a, suffix=f"a{suffix}")
        client_b = _insert_client(conn, agency_id=agency_b, suffix=f"b{suffix}")
        listing_a = _insert_listing(conn, agency_id=agency_a, suffix=f"a{suffix}")
        listing_b = _insert_listing(conn, agency_id=agency_b, suffix=f"b{suffix}")
        demande_a = _insert_demande(
            conn, agency_id=agency_a, client_id=client_a, suffix=f"a{suffix}"
        )
        demande_b = _insert_demande(
            conn, agency_id=agency_b, client_id=client_b, suffix=f"b{suffix}"
        )
        offer_a = _insert_offer(conn, agency_id=agency_a, listing_id=listing_a, suffix=f"a{suffix}")
        offer_b = _insert_offer(conn, agency_id=agency_b, listing_id=listing_b, suffix=f"b{suffix}")
        contract_a = _insert_contract(
            conn,
            agency_id=agency_a,
            client_id=client_a,
            listing_id=listing_a,
            suffix=f"a{suffix}",
        )
        contract_b = _insert_contract(
            conn,
            agency_id=agency_b,
            client_id=client_b,
            listing_id=listing_b,
            suffix=f"b{suffix}",
        )
        location_id = _insert_location(conn, suffix=suffix)
        storage_a = _insert_storage_object(
            conn, agency_id=agency_a, user_id=user_a, suffix=f"a{suffix}"
        )
        storage_b = _insert_storage_object(
            conn, agency_id=agency_b, user_id=user_b, suffix=f"b{suffix}"
        )
        yield {
            "conn": conn,
            "agency_a": agency_a,
            "agency_b": agency_b,
            "client_a": client_a,
            "client_b": client_b,
            "listing_a": listing_a,
            "listing_b": listing_b,
            "demande_a": demande_a,
            "demande_b": demande_b,
            "offer_a": offer_a,
            "offer_b": offer_b,
            "contract_a": contract_a,
            "contract_b": contract_b,
            "location_id": location_id,
            "storage_a": storage_a,
            "storage_b": storage_b,
        }
    finally:
        conn.rollback()
        conn.close()


def _assert_rejected(conn, sql: str, params: tuple[object, ...]) -> None:
    savepoint = f"sp_{uuid.uuid4().hex[:8]}"
    conn.execute(f"SAVEPOINT {savepoint}")
    with pytest.raises(psycopg.Error):
        conn.execute(sql, params).fetchone()
    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
    conn.execute(f"RELEASE SAVEPOINT {savepoint}")


def _assert_allowed(conn, sql: str, params: tuple[object, ...]) -> None:
    savepoint = f"sp_{uuid.uuid4().hex[:8]}"
    conn.execute(f"SAVEPOINT {savepoint}")
    conn.execute(sql, params).fetchone()
    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
    conn.execute(f"RELEASE SAVEPOINT {savepoint}")


def test_cross_tenant_raw_inserts_are_rejected(tenant_fixture) -> None:
    conn = tenant_fixture["conn"]
    location_id = tenant_fixture["location_id"]
    cases = (
        (
            """
            INSERT INTO demandes (
                client_id, agency_id, type, type_id, action, action_id, wilaya, wilaya_id,
                locations, beds_min, surface_min, surface_max, budget_min, budget_max,
                budget_range, surface_range, beds_range, floor_min, floor_max,
                elevator, accessibility_required, created_at, updated_at
            )
            VALUES (
                %s, %s, 'apartment', 1, 'buy', 1, 'Alger', 16,
                'Hydra X', 2, 60, 120, 100, 300,
                numrange(100::numeric, 300::numeric, '[]'),
                numrange(60::numeric, 120::numeric, '[]'),
                int4range(2, NULL, '[]'),
                0, 8, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            RETURNING id
            """,
            (tenant_fixture["client_a"], tenant_fixture["agency_b"]),
        ),
        (
            """
            INSERT INTO offers (
                listing_id, agency_id, type, type_id, action, action_id, status,
                wilaya, wilaya_id, location, beds, surface, budget,
                floor, elevator, accessibility_supported, created_at, updated_at
            )
            VALUES (
                %s, %s, 'apartment', 1, 'sell', 3, 'available',
                'Alger', 16, 'Hydra Y', 3, 90, 200,
                2, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            RETURNING id
            """,
            (tenant_fixture["listing_a"], tenant_fixture["agency_b"]),
        ),
        (
            """
            INSERT INTO visits (
                client_id, listing_id, agency_id, scheduled_date, scheduled_time,
                status, created_at, updated_at
            )
            VALUES (%s, %s, %s, CURRENT_DATE, '10:00', 'scheduled', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (tenant_fixture["client_a"], tenant_fixture["listing_b"], tenant_fixture["agency_a"]),
        ),
        (
            """
            INSERT INTO contracts (
                client_id, listing_id, agency_id, contract_type, status,
                amount, deposit, terms, notes, created_at, updated_at
            )
            VALUES (%s, %s, %s, 'sale', 'draft', 1000, 100, 'terms', 'notes', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (tenant_fixture["client_a"], tenant_fixture["listing_b"], tenant_fixture["agency_a"]),
        ),
        (
            """
            INSERT INTO contract_articles (
                contract_id, agency_id, article_number, title, content, created_at, updated_at
            )
            VALUES (%s, %s, 1, 'Article', 'Body', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (tenant_fixture["contract_a"], tenant_fixture["agency_b"]),
        ),
        (
            """
            INSERT INTO demande_locations (demande_id, agency_id, location_id)
            VALUES (%s, %s, %s)
            RETURNING demande_id
            """,
            (tenant_fixture["demande_a"], tenant_fixture["agency_b"], location_id),
        ),
        (
            """
            INSERT INTO offer_locations (offer_id, agency_id, location_id)
            VALUES (%s, %s, %s)
            RETURNING offer_id
            """,
            (tenant_fixture["offer_a"], tenant_fixture["agency_b"], location_id),
        ),
        (
            """
            INSERT INTO offer_photos (
                offer_id, agency_id, storage_id, position, created_at, updated_at
            )
            VALUES (%s, %s, %s, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (tenant_fixture["offer_a"], tenant_fixture["agency_b"], tenant_fixture["storage_a"]),
        ),
        (
            """
            INSERT INTO match_candidates (demande_id, offer_id, agency_id)
            VALUES (%s, %s, %s)
            RETURNING demande_id
            """,
            (tenant_fixture["demande_a"], tenant_fixture["offer_b"], tenant_fixture["agency_a"]),
        ),
        (
            """
            INSERT INTO match_pairs (demande_id, offer_id, agency_id, score, rank)
            VALUES (%s, %s, %s, 1.0, 1)
            RETURNING demande_id
            """,
            (tenant_fixture["demande_a"], tenant_fixture["offer_b"], tenant_fixture["agency_a"]),
        ),
    )

    for sql, params in cases:
        _assert_rejected(conn, sql, params)


def test_same_tenant_raw_inserts_succeed(tenant_fixture) -> None:
    conn = tenant_fixture["conn"]
    location_id = tenant_fixture["location_id"]
    cases = (
        (
            """
            INSERT INTO visits (
                client_id, listing_id, agency_id, scheduled_date, scheduled_time,
                status, created_at, updated_at
            )
            VALUES (%s, %s, %s, CURRENT_DATE, '10:00', 'scheduled', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (tenant_fixture["client_a"], tenant_fixture["listing_a"], tenant_fixture["agency_a"]),
        ),
        (
            """
            INSERT INTO contract_articles (
                contract_id, agency_id, article_number, title, content, created_at, updated_at
            )
            VALUES (%s, %s, 2, 'Article', 'Body', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (tenant_fixture["contract_a"], tenant_fixture["agency_a"]),
        ),
        (
            """
            INSERT INTO demande_locations (demande_id, agency_id, location_id)
            VALUES (%s, %s, %s)
            RETURNING demande_id
            """,
            (tenant_fixture["demande_a"], tenant_fixture["agency_a"], location_id),
        ),
        (
            """
            INSERT INTO offer_locations (offer_id, agency_id, location_id)
            VALUES (%s, %s, %s)
            RETURNING offer_id
            """,
            (tenant_fixture["offer_a"], tenant_fixture["agency_a"], location_id),
        ),
        (
            """
            INSERT INTO offer_photos (
                offer_id, agency_id, storage_id, position, created_at, updated_at
            )
            VALUES (%s, %s, %s, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (tenant_fixture["offer_a"], tenant_fixture["agency_a"], tenant_fixture["storage_a"]),
        ),
        (
            """
            INSERT INTO match_candidates (demande_id, offer_id, agency_id)
            VALUES (%s, %s, %s)
            RETURNING demande_id
            """,
            (tenant_fixture["demande_a"], tenant_fixture["offer_a"], tenant_fixture["agency_a"]),
        ),
        (
            """
            INSERT INTO match_pairs (demande_id, offer_id, agency_id, score, rank)
            VALUES (%s, %s, %s, 1.0, 1)
            RETURNING demande_id
            """,
            (tenant_fixture["demande_a"], tenant_fixture["offer_a"], tenant_fixture["agency_a"]),
        ),
    )

    for sql, params in cases:
        _assert_allowed(conn, sql, params)
