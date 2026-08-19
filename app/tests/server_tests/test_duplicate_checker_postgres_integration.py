from __future__ import annotations

import uuid

import pytest

pytest.importorskip(
    "psycopg",
    reason="duplicate checker integration tests require server dependencies",
)

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    ensure_django,
)
from core.data import client_repo_write
from server.pg.schema import ensure_schema
from server.pg.uow import get_uow, use_security_context
from server.services.clients import normalize_client_data
from server.services.duplicate_checker import DatabaseDuplicateChecker


def test_database_duplicate_checker_respects_rls_and_entity_tables() -> None:
    ensure_django()
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone = "0555123456"
    normalized_phone = "+213555123456"

    agency_a_id = 0
    agency_b_id = 0
    client_a_id = 0
    client_b_id = 0
    listing_a_id = 0

    conn = admin_conn()
    try:
        agency_a_id = create_agency(conn, f"DCA{suffix}", f"DupCheck Agency A {suffix}")
        agency_b_id = create_agency(conn, f"DCB{suffix}", f"DupCheck Agency B {suffix}")
        row_b = conn.execute(
            """
            INSERT INTO clients (family_name, phone, agency_id, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (f"Client B {suffix}", phone, agency_b_id),
        ).fetchone()
        assert row_b is not None
        client_b_id = int(row_b["id"])
        conn.commit()

        checker = DatabaseDuplicateChecker()

        # Tenant A should not see tenant B's existing phone due to RLS.
        with use_security_context(agency_id=agency_a_id, is_superuser=False):
            with get_uow().session() as session:
                clean_rows, duplicate_rows = checker.filter_batch(
                    [{"phone": normalized_phone}],
                    "client",
                    session,
                )
        assert len(duplicate_rows) == 0
        assert len(clean_rows) == 1

        row_a = conn.execute(
            """
            INSERT INTO clients (family_name, phone, agency_id, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (f"Client A {suffix}", phone, agency_a_id),
        ).fetchone()
        assert row_a is not None
        client_a_id = int(row_a["id"])
        listing_row = conn.execute(
            """
            INSERT INTO listings (family_name, phone, agency_id, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'available', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (f"Listing A {suffix}", "0666000000", agency_a_id),
        ).fetchone()
        assert listing_row is not None
        listing_a_id = int(listing_row["id"])
        conn.commit()

        with use_security_context(agency_id=agency_a_id, is_superuser=False):
            with get_uow().session() as session:
                clean_rows, duplicate_rows = checker.filter_batch(
                    [{"phone": normalized_phone}],
                    "client",
                    session,
                )
                clean_listing_rows, duplicate_listing_rows = checker.filter_batch(
                    [{"phone": "0666000000"}],
                    "listing",
                    session,
                )

        assert len(clean_rows) == 0
        assert len(duplicate_rows) == 1
        assert duplicate_rows[0]["phone"] == normalized_phone
        assert len(clean_listing_rows) == 0
        assert len(duplicate_listing_rows) == 1
    finally:
        if client_a_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_a_id,))
        if client_b_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_b_id,))
        if listing_a_id:
            conn.execute("DELETE FROM listings WHERE id = %s", (listing_a_id,))
        if agency_a_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_a_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_a_id,))
        if agency_b_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_b_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_b_id,))
        conn.commit()
        conn.close()


def test_database_duplicate_checker_matches_ale_masked_phone_rows() -> None:
    ensure_django()
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    agency_id = 0
    client_id = 0

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"DCP{suffix}", f"DupCheck ALE Agency {suffix}")
        conn.commit()

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as write_session:
                prepared = normalize_client_data(
                    {
                        "family_name": f"Client ALE {suffix}",
                        "phone": "+213 555 12 34 56",
                        "status": "active",
                    }
                )
                client_id = client_repo_write.insert_clients_batch(write_session, [prepared])[0]

        checker = DatabaseDuplicateChecker()
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session() as session:
                clean_rows, duplicate_rows = checker.filter_batch(
                    [{"phone": "0555123456"}],
                    "client",
                    session,
                )

        assert clean_rows == []
        assert len(duplicate_rows) == 1
        assert duplicate_rows[0]["phone"] == "0555123456"
    finally:
        if client_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        if agency_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()


def test_database_duplicate_checker_supports_mixed_masked_and_legacy_plaintext_rows() -> None:
    ensure_django()
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    agency_id = 0
    masked_client_id = 0
    legacy_client_id = 0

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"DCM{suffix}", f"DupCheck Mixed Agency {suffix}")
        conn.commit()

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as write_session:
                prepared = normalize_client_data(
                    {
                        "family_name": f"Client ALE {suffix}",
                        "phone": "+213 555 12 34 56",
                        "status": "active",
                    }
                )
                masked_client_id = client_repo_write.insert_clients_batch(
                    write_session, [prepared]
                )[0]

        row = conn.execute(
            """
            INSERT INTO clients (family_name, phone, agency_id, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (f"Client Legacy {suffix}", "0666123456", agency_id),
        ).fetchone()
        assert row is not None
        legacy_client_id = int(row["id"])
        conn.commit()

        checker = DatabaseDuplicateChecker()
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session() as session:
                result = checker.check_phones(
                    [
                        {"row": 1, "data": {"phone": "0555123456", "family_name": "Masked"}},
                        {"row": 2, "data": {"phone": "+213 666 12 34 56", "family_name": "Legacy"}},
                    ],
                    "client",
                    session,
                )

        assert result.clean_indices == set()
        matches_by_row = {match.row_index: match for match in result.matches}
        assert {1, 2} == set(matches_by_row)
        assert matches_by_row[1].candidates[0].existing_id == masked_client_id
        assert matches_by_row[2].candidates[0].existing_id == legacy_client_id
    finally:
        if masked_client_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (masked_client_id,))
        if legacy_client_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (legacy_client_id,))
        if agency_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()
