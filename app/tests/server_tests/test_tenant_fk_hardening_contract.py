from __future__ import annotations

import pytest

pytest.importorskip("psycopg", reason="tenant FK hardening contract tests require server deps")

from app.tests.server_tests._integration_auth_helpers import admin_conn, ensure_django
from server.pg.schema import ensure_schema

_PARENT_UNIQUES = (
    ("clients", "uq_clients_agency_id_id"),
    ("listings", "uq_listings_agency_id_id"),
    ("demandes", "uq_demandes_agency_id_id"),
    ("offers", "uq_offers_agency_id_id"),
    ("contracts", "uq_contracts_agency_id_id"),
)

_TENANT_FKS = (
    ("demandes", "fk_demandes_client_tenant"),
    ("offers", "fk_offers_listing_tenant"),
    ("visits", "fk_visits_client_tenant"),
    ("visits", "fk_visits_listing_tenant"),
    ("contracts", "fk_contracts_client_tenant"),
    ("contracts", "fk_contracts_listing_tenant"),
    ("contract_articles", "fk_contract_articles_contract_tenant"),
    ("demande_locations", "fk_demande_locations_demande_tenant"),
    ("offer_locations", "fk_offer_locations_offer_tenant"),
    ("offer_photos", "fk_offer_photos_offer_tenant"),
    ("match_candidates", "fk_match_candidates_demande_tenant"),
    ("match_candidates", "fk_match_candidates_offer_tenant"),
    ("match_pairs", "fk_match_pairs_demande_tenant"),
    ("match_pairs", "fk_match_pairs_offer_tenant"),
)

_NOT_NULL_TABLES = (
    "clients",
    "listings",
    "demandes",
    "offers",
    "visits",
    "contracts",
    "contract_articles",
    "demande_locations",
    "offer_locations",
    "offer_photos",
    "match_candidates",
    "match_pairs",
)


def _column_not_null(conn, table: str, column: str) -> bool:
    row = conn.execute(
        """
        SELECT is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    ).fetchone()
    return bool(row and row.get("is_nullable") == "NO")


def _has_constraint(conn, table: str, name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE c.conname = %s
          AND n.nspname = 'public'
          AND t.relname = %s
        """,
        (name, table),
    ).fetchone()
    return row is not None


def test_parent_tables_have_tenant_qualified_uniques() -> None:
    ensure_django()
    ensure_schema()
    conn = admin_conn()
    try:
        for table, constraint_name in _PARENT_UNIQUES:
            assert _has_constraint(conn, table, constraint_name), constraint_name
    finally:
        conn.close()


def test_hardened_child_tables_have_composite_tenant_foreign_keys() -> None:
    ensure_django()
    ensure_schema()
    conn = admin_conn()
    try:
        for table, constraint_name in _TENANT_FKS:
            assert _has_constraint(conn, table, constraint_name), constraint_name
    finally:
        conn.close()


def test_hardened_tables_require_agency_id() -> None:
    ensure_django()
    ensure_schema()
    conn = admin_conn()
    try:
        for table in _NOT_NULL_TABLES:
            assert _column_not_null(conn, table, "agency_id"), table
    finally:
        conn.close()


def test_match_counts_cache_tenant_pattern_is_preserved() -> None:
    ensure_django()
    ensure_schema()
    conn = admin_conn()
    try:
        assert _has_constraint(conn, "clients", "uq_clients_agency_id_id")
        assert _has_constraint(conn, "match_counts_cache", "match_counts_cache_pkey")
        assert _has_constraint(conn, "match_counts_cache", "fk_match_counts_cache_client_tenant")
        assert _column_not_null(conn, "match_counts_cache", "agency_id")
    finally:
        conn.close()
