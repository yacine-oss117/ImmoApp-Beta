"""
Schema constraint guardrails for storage ownership + matching inputs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from core.env_files import resolve_env_file

pytest.importorskip("psycopg", reason="Schema constraint tests require psycopg (server venv)")
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from server.pg.schema import ensure_schema  # noqa: E402

_ENV_LOADED = False


def _load_env() -> None:
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
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for schema constraint tests")
    return value


def _admin_conn() -> psycopg.Connection:
    _load_env()
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = _require_env("POSTGRES_DB")
    user = _require_env("POSTGRES_ADMIN_USER")
    password = _require_env("POSTGRES_ADMIN_PASSWORD")
    return psycopg.connect(
        f"host={host} port={port} dbname={dbname} user={user} password={password}",
        row_factory=dict_row,
    )


def _has_accounts_user(conn: psycopg.Connection) -> bool:
    row = conn.execute("SELECT to_regclass('public.accounts_user') AS name").fetchone()
    return bool(row and row.get("name"))


def _column_not_null(conn: psycopg.Connection, table: str, column: str) -> bool:
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


def _column_default(conn: psycopg.Connection, table: str, column: str) -> str | None:
    row = conn.execute(
        """
        SELECT column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    ).fetchone()
    return str(row.get("column_default")) if row and row.get("column_default") else None


def _has_constraint(conn: psycopg.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pg_constraint WHERE conname = %s",
        (name,),
    ).fetchone()
    return row is not None


def test_storage_ownership_constraints() -> None:
    ensure_schema()
    conn = _admin_conn()
    assert _column_not_null(conn, "storage_objects", "user_id")
    assert _column_not_null(conn, "storage_objects", "role")
    assert _has_constraint(conn, "chk_storage_objects_role")
    assert _has_constraint(conn, "chk_storage_events_role")

    if _has_accounts_user(conn):
        assert _has_constraint(conn, "fk_storage_objects_user")
        assert _has_constraint(conn, "fk_storage_events_user")
        assert _has_constraint(conn, "fk_record_acl_user")
    conn.close()


def test_matching_constraints_and_defaults() -> None:
    ensure_schema()
    conn = _admin_conn()

    # Demande required columns
    for col in (
        "action_id",
        "type_id",
        "wilaya_id",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
    ):
        assert _column_not_null(conn, "demandes", col), f"demandes.{col} should be NOT NULL"

    # Range defaults must exist and be NOT NULL
    for col in ("budget_range", "surface_range", "beds_range"):
        assert _column_not_null(conn, "demandes", col), f"demandes.{col} should be NOT NULL"
        assert _column_default(conn, "demandes", col) is not None

    # Offer required columns
    for col in (
        "action_id",
        "type_id",
        "wilaya_id",
        "location",
        "beds",
        "surface",
        "budget",
        "floor",
        "elevator",
        "accessibility_supported",
    ):
        assert _column_not_null(conn, "offers", col), f"offers.{col} should be NOT NULL"

    # property_types.requires_floor exists
    row = conn.execute("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'property_types'
          AND column_name = 'requires_floor'
        """).fetchone()
    assert row is not None, "property_types.requires_floor column missing"

    conn.close()
