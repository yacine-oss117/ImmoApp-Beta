from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import django
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from dotenv import load_dotenv

from core.env_files import resolve_env_file

pytest.importorskip("psycopg", reason="RLS breach matrix tests require server dependencies")
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
django.setup()

from app.tests.server_tests._integration_auth_helpers import (  # noqa: E402
    cleanup_import_test_agency,
)
from server.api.tasks_match_cache import fetch_match_cache_all_task  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import get_uow, use_security_context  # noqa: E402
from server.services import clients as client_service  # noqa: E402

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
        raise RuntimeError(f"{name} is required for RLS breach matrix tests")
    return value


def _admin_conn() -> psycopg.Connection:
    _load_env()
    return psycopg.connect(
        (
            f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
            f"port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"dbname={_require_env('POSTGRES_DB')} "
            f"user={_require_env('POSTGRES_ADMIN_USER')} "
            f"password={_require_env('POSTGRES_ADMIN_PASSWORD')}"
        ),
        row_factory=dict_row,
    )


def _create_agency(conn: psycopg.Connection, code: str, label: str) -> int:
    row = conn.execute(
        """
        INSERT INTO accounts_agency (
            legal_name, display_name, agency_code,
            kbis_number, phone_number, phone_number_enc, email,
            address_line1, address_line1_enc, address_line2, address_line2_enc, city, city_enc, postal_code, country,
            is_active, max_users, max_managers, max_agents_per_manager,
            created_at, updated_at
        )
        VALUES (
            %s, %s, %s,
            '', '', '', '',
            '', '', '', '', '', '', '', '',
            true, 3, 1, 2,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (label, label, code),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _create_manager_user(
    conn: psycopg.Connection, *, agency_id: int, username: str, password: str
) -> int:
    row = conn.execute(
        """
        INSERT INTO accounts_user (
            password, last_login, is_superuser, username,
            first_name, first_name_enc, first_name_search_src,
            last_name, last_name_enc, last_name_search_src,
            email,
            is_staff, is_active, date_joined,
            role, agency_id, manager_id, access_scope, is_owner, can_hard_delete,
            can_import, import_granted_by_id, timezone, locale,
            mfa_totp_secret, mfa_totp_secret_enc
        )
        VALUES (
            %s, NULL, false, %s, '', '', '', '', '', '', '',
            false, true, CURRENT_TIMESTAMP,
            'manager', %s, NULL, 'agency', false, false,
            false, NULL, '', '',
            '', ''
        )
        RETURNING id
        """,
        (make_password(password), username, agency_id),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _token_for(username: str, password: str) -> str:
    client = Client()
    response = client.post(
        "/api/auth/token/",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    assert response.status_code == 200, response.content.decode("utf-8", errors="ignore")
    payload = response.json()
    token = payload.get("access")
    assert isinstance(token, str) and token
    return token


def test_rls_breach_matrix_api_service_task_and_exception_path() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]

    username_a = f"rls_matrix_a_{suffix}"
    username_b = f"rls_matrix_b_{suffix}"
    password = "StrongTestPass_123!"
    marker_a = f"RLS_MATRIX_A_{suffix}"
    marker_b = f"RLS_MATRIX_B_{suffix}"

    agency_a_id = 0
    agency_b_id = 0
    user_a_id = 0
    user_b_id = 0
    client_a_id = 0
    client_b_id = 0

    conn = _admin_conn()
    try:
        agency_a_id = _create_agency(conn, f"RMXA{suffix}", f"RLS Matrix Agency A {suffix}")
        agency_b_id = _create_agency(conn, f"RMXB{suffix}", f"RLS Matrix Agency B {suffix}")
        user_a_id = _create_manager_user(
            conn, agency_id=agency_a_id, username=username_a, password=password
        )
        user_b_id = _create_manager_user(
            conn, agency_id=agency_b_id, username=username_b, password=password
        )
        conn.commit()

        token_a = _token_for(username_a, password)
        token_b = _token_for(username_b, password)
        web = Client()

        create_a = web.post(
            "/api/v1/clients/",
            data=json.dumps({"family_name": marker_a, "phone": "213555111111"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
        )
        assert create_a.status_code == 201, create_a.content.decode("utf-8", errors="ignore")
        client_a_id = int(create_a.json()["id"])

        create_b = web.post(
            "/api/v1/clients/",
            data=json.dumps({"family_name": marker_b, "phone": "213555222222"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
        )
        assert create_b.status_code == 201, create_b.content.decode("utf-8", errors="ignore")
        client_b_id = int(create_b.json()["id"])

        # API layer isolation check (cannot read foreign detail)
        foreign_detail = web.get(
            f"/api/v1/clients/{client_b_id}/",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
        )
        assert foreign_detail.status_code in (403, 404)

        # Service layer isolation check (context-bound UoW reads)
        with use_security_context(agency_id=agency_a_id, is_superuser=False):
            assert client_service.get_client_by_id(client_b_id) is None
            items = client_service.fetch_clients(
                limit=200,
                offset=0,
                search=marker_b,
                status="active",
                include_deleted=False,
            )
            assert all(int(item.id) != client_b_id for item in items)

        # Seed cache rows for task-level isolation probe.
        conn.execute(
            """
            INSERT INTO match_counts_cache (
                client_id, agency_id, count, visibility, owner_user_id, computed_at, is_dirty
            )
            VALUES (%s, %s, 11, 'agency', NULL, CURRENT_TIMESTAMP, 0)
            ON CONFLICT (agency_id, client_id) DO UPDATE
            SET
                count = EXCLUDED.count,
                visibility = EXCLUDED.visibility,
                owner_user_id = EXCLUDED.owner_user_id,
                computed_at = EXCLUDED.computed_at,
                is_dirty = 0
            """,
            (client_a_id, agency_a_id),
        )
        conn.execute(
            """
            INSERT INTO match_counts_cache (
                client_id, agency_id, count, visibility, owner_user_id, computed_at, is_dirty
            )
            VALUES (%s, %s, 22, 'agency', NULL, CURRENT_TIMESTAMP, 0)
            ON CONFLICT (agency_id, client_id) DO UPDATE
            SET
                count = EXCLUDED.count,
                visibility = EXCLUDED.visibility,
                owner_user_id = EXCLUDED.owner_user_id,
                computed_at = EXCLUDED.computed_at,
                is_dirty = 0
            """,
            (client_b_id, agency_b_id),
        )
        conn.commit()

        # Task entrypoint isolation check.
        counts_a = fetch_match_cache_all_task.run(agency_id=agency_a_id)["counts"]
        counts_b = fetch_match_cache_all_task.run(agency_id=agency_b_id)["counts"]
        assert int(client_b_id) not in {int(k) for k in counts_a.keys()}
        assert int(client_a_id) not in {int(k) for k in counts_b.keys()}

        # Pool reuse after rollback/exception path: no leaked context.
        with use_security_context(agency_id=agency_a_id, is_superuser=False):
            with pytest.raises(RuntimeError):
                with get_uow().transaction() as session:
                    session.execute("SELECT set_config('app.actor_id', '777', false)")
                    session.execute(
                        "SELECT set_config('app.actor_email', 'leak@test.local', false)"
                    )
                    raise RuntimeError("force rollback")

        with use_security_context(agency_id=None, is_superuser=False):
            with get_uow().session() as session:
                row = session.execute("""
                    SELECT
                        current_setting('app.current_agency_id', true) AS agency,
                        current_setting('app.actor_id', true) AS actor_id,
                        current_setting('app.actor_email', true) AS actor_email
                    """).fetchone()
                assert row is not None
                assert row["agency"] == "", "Leaked agency_id after exception/rollback"
                assert row["actor_id"] == "", "Leaked actor_id after exception/rollback"
                assert row["actor_email"] == "", "Leaked actor_email after exception/rollback"
    finally:
        conn.rollback()
        conn.close()
        if agency_a_id:
            cleanup_import_test_agency(agency_id=agency_a_id, user_id=user_a_id)
        if agency_b_id:
            cleanup_import_test_agency(agency_id=agency_b_id, user_id=user_b_id)
