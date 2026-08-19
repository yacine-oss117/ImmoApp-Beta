"""
Tenant Isolation Tests - RLS Verification

These tests verify Row Level Security (RLS) at the database level.
They connect as 'immoapp_app' (non-superuser) to properly test RLS enforcement.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from core.env_files import resolve_env_file

# Skip entire module if server dependencies are not available (e.g., running in client venv)
pytest.importorskip("psycopg", reason="RLS tests require psycopg (server venv)")
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from server.pg.schema import ensure_schema  # noqa: E402

_ENV_LOADED = False


def _load_env() -> None:
    """Load environment variables from the configured local env file once."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    repo_root = Path(__file__).resolve().parents[3]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path)
    _ENV_LOADED = True


def _require_env(name: str) -> str:
    """Return a required environment variable or raise."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for tenant isolation tests")
    return value


def _build_conn_info(user_env: str, password_env: str) -> str:
    _load_env()
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = _require_env("POSTGRES_DB")
    user = _require_env(user_env)
    password = _require_env(password_env)
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def _get_app_connection() -> psycopg.Connection:
    """Get a connection as the non-superuser app role (RLS enforced)."""
    return psycopg.connect(
        _build_conn_info("POSTGRES_USER", "POSTGRES_PASSWORD"), row_factory=dict_row
    )


def _get_admin_connection() -> psycopg.Connection:
    """Get a connection as the superuser role (for setup/cleanup)."""
    return psycopg.connect(
        _build_conn_info("POSTGRES_ADMIN_USER", "POSTGRES_ADMIN_PASSWORD"),
        row_factory=dict_row,
    )


def _ensure_agency(admin_conn: psycopg.Connection, code: str, name: str) -> int:
    row = admin_conn.execute(
        """
        INSERT INTO accounts_agency (
            legal_name,
            display_name,
            agency_code,
            kbis_number,
            phone_number,
            phone_number_enc,
            email,
            address_line1,
            address_line1_enc,
            address_line2,
            address_line2_enc,
            city,
            city_enc,
            postal_code,
            country,
            is_active,
            max_users,
            max_managers,
            max_agents_per_manager,
            created_at,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            true,
            3,
            1,
            2,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (agency_code) DO UPDATE
        SET updated_at = EXCLUDED.updated_at
        RETURNING id
        """,
        (name, name, code),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _ensure_test_agencies(admin_conn: psycopg.Connection) -> tuple[int, int]:
    agency1_id = _ensure_agency(admin_conn, "TEST_RLS_AGENCY_1", "Test RLS Agency 1")
    agency2_id = _ensure_agency(admin_conn, "TEST_RLS_AGENCY_2", "Test RLS Agency 2")
    return agency1_id, agency2_id


def _ensure_acl_user(admin_conn: psycopg.Connection, *, user_id: int, agency_id: int) -> None:
    admin_conn.execute(
        """
        INSERT INTO accounts_user (
            id,
            password,
            last_login,
            is_superuser,
            username,
            first_name,
            first_name_enc,
            first_name_search_src,
            last_name,
            last_name_enc,
            last_name_search_src,
            email,
            is_staff,
            is_active,
            date_joined,
            role,
            agency_id,
            manager_id,
            access_scope,
            is_owner,
            can_hard_delete,
            can_import,
            import_granted_by_id,
            timezone,
            locale,
            mfa_totp_secret,
            mfa_totp_secret_enc
        )
        VALUES (
            %s,
            '!',
            NULL,
            false,
            %s,
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            false,
            true,
            CURRENT_TIMESTAMP,
            'manager',
            %s,
            NULL,
            'agency',
            false,
            false,
            false,
            NULL,
            '',
            '',
            '',
            ''
        )
        ON CONFLICT (id) DO UPDATE
        SET agency_id = EXCLUDED.agency_id,
            role = EXCLUDED.role,
            access_scope = EXCLUDED.access_scope,
            is_active = EXCLUDED.is_active
        """,
        (user_id, f"rls_acl_user_{user_id}", agency_id),
    )


def test_rls_isolation_database_level():
    """
    PROVE that RLS works at the database level.
    This test bypasses application logic and uses raw SQL to attempt 'stealing' data.
    """
    ensure_schema()
    # Use unique markers to avoid collisions with other test runs
    agency1_marker = "TEST_RLS_Agency1_XYZ123"
    agency2_marker = "TEST_RLS_Agency2_XYZ123"

    # 1. Cleanup and Setup Phase: Use superuser connection
    admin_conn = _get_admin_connection()
    agency1_id, agency2_id = _ensure_test_agencies(admin_conn)
    admin_conn.execute(
        "DELETE FROM clients WHERE family_name IN (%s, %s)", (agency1_marker, agency2_marker)
    )
    admin_conn.execute(
        "INSERT INTO clients (family_name, phone, agency_id) VALUES (%s, %s, %s)",
        (agency1_marker, "111111", agency1_id),
    )
    admin_conn.execute(
        "INSERT INTO clients (family_name, phone, agency_id) VALUES (%s, %s, %s)",
        (agency2_marker, "222222", agency2_id),
    )
    admin_conn.commit()
    admin_conn.close()

    # 2. Verification Phase: Use non-superuser connection (RLS enforced!)
    app_conn = _get_app_connection()

    # Test as Agency 1
    app_conn.execute("SELECT set_config('app.current_agency_id', %s, false)", (str(agency1_id),))
    app_conn.execute("SELECT set_config('app.is_superuser', 'false', false)")
    rows = app_conn.execute("SELECT family_name FROM clients").fetchall()
    family_names = [row["family_name"] for row in rows]

    assert agency1_marker in family_names, "Agency 1 should see its own data"
    assert agency2_marker not in family_names, "RLS FAILURE: Agency 1 detected Agency 2 data!"

    # Test as Agency 2
    app_conn.execute("SELECT set_config('app.current_agency_id', %s, false)", (str(agency2_id),))
    rows = app_conn.execute("SELECT family_name FROM clients").fetchall()
    family_names = [row["family_name"] for row in rows]

    assert agency2_marker in family_names, "Agency 2 should see its own data"
    assert agency1_marker not in family_names, "RLS FAILURE: Agency 2 detected Agency 1 data!"

    # Test superuser bypass via app.is_superuser flag
    app_conn.execute("SELECT set_config('app.is_superuser', 'true', false)")
    rows = app_conn.execute("SELECT family_name FROM clients").fetchall()
    family_names = [row["family_name"] for row in rows]

    assert agency1_marker in family_names, "Superuser should see Agency 1 data"
    assert agency2_marker in family_names, "Superuser should see Agency 2 data"

    app_conn.close()

    # 3. Cleanup
    admin_conn = _get_admin_connection()
    admin_conn.execute(
        "DELETE FROM clients WHERE family_name IN (%s, %s)", (agency1_marker, agency2_marker)
    )
    admin_conn.commit()
    admin_conn.close()


def test_rls_blocks_unauthorized_inserts():
    """
    Confirm that an agency cannot 'poison' another agency's data
    by trying to insert a record with another agency's ID.
    """
    ensure_schema()
    app_conn = _get_app_connection()
    admin_conn = _get_admin_connection()
    agency1_id, agency2_id = _ensure_test_agencies(admin_conn)
    admin_conn.commit()
    admin_conn.close()

    # Set context as Agency 1
    app_conn.execute("SELECT set_config('app.current_agency_id', %s, false)", (str(agency1_id),))
    app_conn.execute("SELECT set_config('app.is_superuser', 'false', false)")

    # Attempt to insert with agency_id = 2 (should be blocked by RLS WITH CHECK)
    with pytest.raises(psycopg.errors.Error):
        app_conn.execute(
            "INSERT INTO clients (family_name, phone, agency_id) VALUES (%s, %s, %s)",
            ("Poison_Attempt_Test", "999", agency2_id),
        )

    app_conn.close()


def test_all_tenant_tables_have_rls_active():
    """
    Verify that all expected tenant tables have RLS enabled in the live DB.
    """
    ensure_schema()
    tenant_tables = [
        "clients",
        "listings",
        "demandes",
        "offers",
        "demande_locations",
        "offer_locations",
        "visits",
        "contracts",
        "contract_articles",
        "wa_templates",
        "audit_logs",
        "auth_security_events",
        "custom_locations",
        "match_counts_cache",
        "match_candidates",
        "match_pairs",
        "record_acl",
        "agency_settings",
    ]

    admin_conn = _get_admin_connection()
    for table in tenant_tables:
        row = admin_conn.execute(
            "SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = %s",
            (table,),
        ).fetchone()

        assert row is not None, f"Table {table} not found in database!"
        assert row["relrowsecurity"] is True, f"RLS is NOT ENABLED on table {table}!"

    admin_conn.close()


def test_rls_visibility_acl() -> None:
    """Verify restricted visibility respects ACL and manager access."""
    ensure_schema()
    admin_conn = _get_admin_connection()
    agency1_id, _agency2_id = _ensure_test_agencies(admin_conn)

    marker = "TEST_RLS_VISIBILITY_CLIENT"
    admin_conn.execute("DELETE FROM record_acl WHERE table_name = 'clients'")
    admin_conn.execute("DELETE FROM clients WHERE family_name = %s", (marker,))
    row = admin_conn.execute(
        "INSERT INTO clients (family_name, phone, agency_id, visibility) "
        "VALUES (%s, %s, %s, 'restricted') RETURNING id",
        (marker, "555555", agency1_id),
    ).fetchone()
    assert row is not None
    client_id = row["id"]
    _ensure_acl_user(admin_conn, user_id=123, agency_id=agency1_id)
    _ensure_acl_user(admin_conn, user_id=456, agency_id=agency1_id)
    admin_conn.execute(
        "INSERT INTO record_acl (table_name, record_id, user_id, agency_id) "
        "VALUES ('clients', %s, %s, %s)",
        (client_id, 123, agency1_id),
    )
    admin_conn.commit()
    admin_conn.close()

    app_conn = _get_app_connection()
    app_conn.execute("SELECT set_config('app.current_agency_id', %s, false)", (str(agency1_id),))
    app_conn.execute("SELECT set_config('app.is_superuser', 'false', false)")
    app_conn.execute("SELECT set_config('app.actor_role', 'agent', false)")
    app_conn.execute("SELECT set_config('app.actor_is_owner', 'false', false)")

    app_conn.execute("SELECT set_config('app.actor_id', '123', false)")
    rows = app_conn.execute("SELECT id FROM clients WHERE id = %s", (client_id,)).fetchall()
    assert rows, "Agent in ACL should see restricted record"

    app_conn.execute("SELECT set_config('app.actor_id', '456', false)")
    rows = app_conn.execute("SELECT id FROM clients WHERE id = %s", (client_id,)).fetchall()
    assert not rows, "Agent without ACL should not see restricted record"

    app_conn.execute("SELECT set_config('app.actor_role', 'manager', false)")
    rows = app_conn.execute("SELECT id FROM clients WHERE id = %s", (client_id,)).fetchall()
    assert rows, "Manager should see restricted record without ACL"

    app_conn.close()

    admin_conn = _get_admin_connection()
    admin_conn.execute(
        "DELETE FROM record_acl WHERE table_name = 'clients' AND record_id = %s", (client_id,)
    )
    admin_conn.execute("DELETE FROM clients WHERE id = %s", (client_id,))
    admin_conn.commit()
    admin_conn.close()
