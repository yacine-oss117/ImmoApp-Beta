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

pytest.importorskip("psycopg", reason="cross-tenant API tests require server dependencies")
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
        raise RuntimeError(f"{name} is required for cross-tenant API tests")
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


def test_api_cross_tenant_read_and_write_are_blocked() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]

    username_a = f"rls_mgr_a_{suffix}"
    username_b = f"rls_mgr_b_{suffix}"
    password = "StrongTestPass_123!"
    marker_a = f"RLS_API_A_{suffix}"
    marker_b = f"RLS_API_B_{suffix}"

    agency_a_id = 0
    agency_b_id = 0
    user_a_id = 0
    user_b_id = 0
    client_a_id = 0
    client_b_id = 0
    listing_a_id = 0
    listing_b_id = 0

    conn = _admin_conn()
    try:
        agency_a_id = _create_agency(conn, f"RLSA{suffix}", f"RLS Agency A {suffix}")
        agency_b_id = _create_agency(conn, f"RLSB{suffix}", f"RLS Agency B {suffix}")
        user_a_id = _create_manager_user(
            conn, agency_id=agency_a_id, username=username_a, password=password
        )
        user_b_id = _create_manager_user(
            conn, agency_id=agency_b_id, username=username_b, password=password
        )
        conn.commit()

        token_a = _token_for(username_a, password)
        token_b = _token_for(username_b, password)
        auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}
        web = Client()

        create_a = web.post(
            "/api/v1/clients/",
            data=json.dumps({"family_name": marker_a, "phone": "213555010101"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert create_a.status_code == 201, create_a.content.decode("utf-8", errors="ignore")
        client_a_id = int(create_a.json()["id"])

        create_b = web.post(
            "/api/v1/clients/",
            data=json.dumps({"family_name": marker_b, "phone": "213555020202"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
        )
        assert create_b.status_code == 201, create_b.content.decode("utf-8", errors="ignore")
        client_b_id = int(create_b.json()["id"])

        own_detail = web.get(
            f"/api/v1/clients/{client_a_id}/", HTTP_HOST="localhost", **auth_headers
        )
        assert own_detail.status_code == 200

        foreign_detail = web.get(
            f"/api/v1/clients/{client_b_id}/", HTTP_HOST="localhost", **auth_headers
        )
        assert foreign_detail.status_code in (403, 404)

        foreign_update = web.put(
            f"/api/v1/clients/{client_b_id}/",
            data=json.dumps({"family_name": "HACKED", "row_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert foreign_update.status_code in (403, 404)

        list_foreign = web.get(
            "/api/v1/clients/",
            data={"search": marker_b, "limit": 100, "offset": 0},
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert list_foreign.status_code == 200
        payload = list_foreign.json()
        assert isinstance(payload, dict)
        items = payload.get("items", [])
        assert isinstance(items, list)
        assert all(int(item.get("id", 0)) != client_b_id for item in items)
        assert all(str(item.get("family_name", "")) != marker_b for item in items)

        cursor_search_own = web.get(
            "/api/v1/clients/",
            data={"search": marker_a, "limit": 100, "cursor": 999999999},
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert cursor_search_own.status_code == 200
        cursor_own_items = cursor_search_own.json().get("items", [])
        assert isinstance(cursor_own_items, list)
        cursor_own_ids = {
            int(item.get("id", 0)) for item in cursor_own_items if isinstance(item, dict)
        }
        assert client_a_id in cursor_own_ids
        assert client_b_id not in cursor_own_ids

        cursor_search_phone = web.get(
            "/api/v1/clients/",
            data={"search": "213555010101", "limit": 100, "cursor": 999999999},
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert cursor_search_phone.status_code == 200
        cursor_phone_items = cursor_search_phone.json().get("items", [])
        assert isinstance(cursor_phone_items, list)
        cursor_phone_ids = {
            int(item.get("id", 0)) for item in cursor_phone_items if isinstance(item, dict)
        }
        assert client_a_id in cursor_phone_ids
        assert client_b_id not in cursor_phone_ids

        list_all = web.get(
            "/api/v1/clients/",
            data={"limit": 100, "offset": 0},
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert list_all.status_code == 200
        all_items = list_all.json().get("items", [])
        assert isinstance(all_items, list)
        all_item_ids = {int(item.get("id", 0)) for item in all_items if isinstance(item, dict)}
        assert client_a_id in all_item_ids
        assert client_b_id not in all_item_ids
        assert all(
            str(item.get("family_name", "")) != marker_b
            for item in all_items
            if isinstance(item, dict)
        )

        owner_b_detail = web.get(
            f"/api/v1/clients/{client_b_id}/",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
        )
        assert owner_b_detail.status_code == 200
        owner_payload = owner_b_detail.json()
        assert str(owner_payload.get("family_name", "")) == marker_b

        listing_marker_a = f"{marker_a}_LISTING"
        listing_marker_b = f"{marker_b}_LISTING"
        create_listing_a = web.post(
            "/api/v1/listings/",
            data=json.dumps({"family_name": listing_marker_a, "phone": "213555030303"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert create_listing_a.status_code == 201, create_listing_a.content.decode(
            "utf-8", errors="ignore"
        )
        listing_a_id = int(create_listing_a.json()["id"])

        create_listing_b = web.post(
            "/api/v1/listings/",
            data=json.dumps({"family_name": listing_marker_b, "phone": "213555040404"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
        )
        assert create_listing_b.status_code == 201, create_listing_b.content.decode(
            "utf-8", errors="ignore"
        )
        listing_b_id = int(create_listing_b.json()["id"])

        list_all_listings = web.get(
            "/api/v1/listings/",
            data={"limit": 100, "offset": 0},
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert list_all_listings.status_code == 200
        listing_items = list_all_listings.json().get("items", [])
        assert isinstance(listing_items, list)
        listing_item_ids = {
            int(item.get("id", 0)) for item in listing_items if isinstance(item, dict)
        }
        assert listing_a_id in listing_item_ids
        assert listing_b_id not in listing_item_ids
        assert all(
            str(item.get("family_name", "")) != listing_marker_b
            for item in listing_items
            if isinstance(item, dict)
        )

        cursor_search_listing = web.get(
            "/api/v1/listings/",
            data={"search": listing_marker_a, "limit": 100, "cursor": 999999999},
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert cursor_search_listing.status_code == 200
        cursor_listing_items = cursor_search_listing.json().get("items", [])
        assert isinstance(cursor_listing_items, list)
        cursor_listing_ids = {
            int(item.get("id", 0)) for item in cursor_listing_items if isinstance(item, dict)
        }
        assert listing_a_id in cursor_listing_ids
        assert listing_b_id not in cursor_listing_ids

        cursor_search_listing_phone = web.get(
            "/api/v1/listings/",
            data={"search": "213555030303", "limit": 100, "cursor": 999999999},
            HTTP_HOST="localhost",
            **auth_headers,
        )
        assert cursor_search_listing_phone.status_code == 200
        cursor_listing_phone_items = cursor_search_listing_phone.json().get("items", [])
        assert isinstance(cursor_listing_phone_items, list)
        cursor_listing_phone_ids = {
            int(item.get("id", 0)) for item in cursor_listing_phone_items if isinstance(item, dict)
        }
        assert listing_a_id in cursor_listing_phone_ids
        assert listing_b_id not in cursor_listing_phone_ids
    finally:
        conn.rollback()
        conn.close()
        if agency_a_id:
            cleanup_import_test_agency(agency_id=agency_a_id, user_id=user_a_id)
        if agency_b_id:
            cleanup_import_test_agency(agency_id=agency_b_id, user_id=user_b_id)
