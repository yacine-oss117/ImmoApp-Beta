from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path

import psycopg
from django.contrib.auth.hashers import make_password
from psycopg.rows import dict_row


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django

    django.setup()


def _assert_status(name: str, status_code: int, expected: tuple[int, ...]) -> None:
    if status_code not in expected:
        raise SystemExit(f"verify_dast_smoke: {name} expected status {expected}, got {status_code}")


def _assert_response(name: str, response, expected: tuple[int, ...]) -> None:
    if response.status_code in expected:
        return
    body = ""
    try:
        body = response.content.decode("utf-8", errors="replace")
    except Exception:
        body = "<unreadable>"
    raise SystemExit(
        f"verify_dast_smoke: {name} expected status {expected}, got {response.status_code}. "
        f"body={body}"
    )


def _db_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"verify_dast_smoke: missing required DB env {name}")
    return value


def _admin_conn() -> psycopg.Connection:
    return psycopg.connect(
        (
            f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
            f"port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"dbname={_db_env('POSTGRES_DB')} "
            f"user={_db_env('POSTGRES_ADMIN_USER')} "
            f"password={_db_env('POSTGRES_ADMIN_PASSWORD')}"
        ),
        row_factory=dict_row,
    )


def _create_agency(conn: psycopg.Connection, *, code: str, label: str) -> int:
    row = conn.execute(
        """
        INSERT INTO accounts_agency (
            legal_name, display_name, agency_code,
            kbis_number, phone_number, email,
            address_line1, address_line2, city, postal_code, country,
            is_active, max_users, max_managers, max_agents_per_manager,
            created_at, updated_at
        )
        VALUES (
            %s, %s, %s,
            '', '', '',
            '', '', '', '', '',
            true, 3, 1, 2,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (label, label, code),
    ).fetchone()
    if not row:
        raise SystemExit("verify_dast_smoke: failed to create agency")
    return int(row["id"])


def _create_manager_user(
    conn: psycopg.Connection, *, agency_id: int, username: str, password: str
) -> int:
    row = conn.execute(
        """
        INSERT INTO accounts_user (
            password, last_login, is_superuser, username, first_name, last_name, email,
            is_staff, is_active, date_joined,
            role, agency_id, manager_id, access_scope, is_owner, can_hard_delete,
            can_import, import_granted_by_id, timezone, locale
        )
        VALUES (
            %s, NULL, false, %s, '', '', '',
            false, true, CURRENT_TIMESTAMP,
            'manager', %s, NULL, 'agency', false, false,
            false, NULL, '', ''
        )
        RETURNING id
        """,
        (make_password(password), username, agency_id),
    ).fetchone()
    if not row:
        raise SystemExit("verify_dast_smoke: failed to create manager user")
    return int(row["id"])


def _token_for(client, *, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/token/",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    _assert_status("auth token", response.status_code, (200,))
    payload = response.json()
    token = payload.get("access")
    if not isinstance(token, str) or not token:
        raise SystemExit("verify_dast_smoke: auth token response missing access token")
    return token


def _run_unauthenticated_smoke(client) -> None:
    live = client.get("/api/v1/health/live/", HTTP_HOST="localhost")
    _assert_status("health/live", live.status_code, (200,))

    protected_get = (
        "/api/v1/clients/",
        "/api/v1/listings/",
        "/api/v1/users/",
        "/api/v1/notifications/",
        "/api/v1/storage/presign/",
    )
    for path in protected_get:
        response = client.get(path, HTTP_HOST="localhost")
        _assert_status(path, response.status_code, (401, 403))

    protected_post = (
        "/api/v1/clients/",
        "/api/v1/storage/presign-upload/",
        "/api/v1/import/presign/",
    )
    for path in protected_post:
        response = client.post(
            path, data={}, content_type="application/json", HTTP_HOST="localhost"
        )
        _assert_status(path, response.status_code, (401, 403))


def _run_authenticated_security_smoke(client) -> None:
    def _idem() -> str:
        return uuid.uuid4().hex

    suffix = uuid.uuid4().hex[:8]
    username_a = f"dast_mgr_a_{suffix}"
    username_b = f"dast_mgr_b_{suffix}"
    password = "StrongDastPass_123!"
    marker_a = f"DAST_A_{suffix}"
    marker_b = f"DAST_B_{suffix}"
    digits = "".join(ch for ch in uuid.uuid4().hex if ch.isdigit())
    if len(digits) < 8:
        digits = (digits + "0123456789")[:8]
    phone_a = f"2135{digits[:8]}"
    phone_b = f"2136{digits[:8]}"

    conn = _admin_conn()
    agency_a_id = 0
    agency_b_id = 0
    user_a_id = 0
    user_b_id = 0
    client_a_id = 0
    client_b_id = 0
    listing_a_id = 0
    listing_b_id = 0
    try:
        agency_a_id = _create_agency(conn, code=f"DASTA{suffix}", label=f"DAST Agency A {suffix}")
        agency_b_id = _create_agency(conn, code=f"DASTB{suffix}", label=f"DAST Agency B {suffix}")
        user_a_id = _create_manager_user(
            conn, agency_id=agency_a_id, username=username_a, password=password
        )
        user_b_id = _create_manager_user(
            conn, agency_id=agency_b_id, username=username_b, password=password
        )
        conn.commit()

        token_a = _token_for(client, username=username_a, password=password)
        token_b = _token_for(client, username=username_b, password=password)

        create_client_a = client.post(
            "/api/v1/clients/",
            data=json.dumps({"family_name": marker_a, "phone": phone_a}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
            HTTP_IDEMPOTENCY_KEY=_idem(),
        )
        _assert_response("create client A", create_client_a, (201,))
        client_a_id = int(create_client_a.json()["id"])

        create_client_b = client.post(
            "/api/v1/clients/",
            data=json.dumps({"family_name": marker_b, "phone": phone_b}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
            HTTP_IDEMPOTENCY_KEY=_idem(),
        )
        _assert_response("create client B", create_client_b, (201,))
        client_b_id = int(create_client_b.json()["id"])

        create_listing_a = client.post(
            "/api/v1/listings/",
            data=json.dumps({"family_name": marker_a, "phone": phone_a}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
            HTTP_IDEMPOTENCY_KEY=_idem(),
        )
        _assert_response("create listing A", create_listing_a, (201,))
        listing_a_id = int(create_listing_a.json()["id"])

        create_listing_b = client.post(
            "/api/v1/listings/",
            data=json.dumps({"family_name": marker_b, "phone": phone_b}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
            HTTP_IDEMPOTENCY_KEY=_idem(),
        )
        _assert_response("create listing B", create_listing_b, (201,))
        listing_b_id = int(create_listing_b.json()["id"])

        foreign_client_read = client.get(
            f"/api/v1/clients/{client_b_id}/",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
        )
        _assert_status("foreign client read", foreign_client_read.status_code, (403, 404))

        foreign_client_write = client.put(
            f"/api/v1/clients/{client_b_id}/",
            data=json.dumps({"family_name": "HACKED", "row_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
            HTTP_IDEMPOTENCY_KEY=_idem(),
        )
        _assert_status("foreign client write", foreign_client_write.status_code, (403, 404))

        foreign_listing_read = client.get(
            f"/api/v1/listings/{listing_b_id}/",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
        )
        _assert_status("foreign listing read", foreign_listing_read.status_code, (403, 404))

        malformed = client.post(
            "/api/v1/clients/",
            data="{malformed-json",
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
            HTTP_IDEMPOTENCY_KEY=_idem(),
        )
        _assert_status("malformed clients payload", malformed.status_code, (400,))

        malformed_import = client.post(
            "/api/v1/import/presign/",
            data=json.dumps({"kind": "unknown"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
            HTTP_IDEMPOTENCY_KEY=_idem(),
        )
        _assert_status("import presign malformed", malformed_import.status_code, (400, 403))

        malformed_storage = client.post(
            "/api/v1/storage/presign-upload/",
            data=json.dumps({"purpose": "x"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
            HTTP_IDEMPOTENCY_KEY=_idem(),
        )
        _assert_status("storage presign malformed", malformed_storage.status_code, (400, 403))

        list_clients = client.get(
            "/api/v1/clients/",
            {"search": marker_b, "limit": 100, "offset": 0},
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
        )
        _assert_status("client list isolation", list_clients.status_code, (200,))
        payload = list_clients.json()
        items = payload.get("items", [])
        if any(int(item.get("id", 0)) == client_b_id for item in items):
            raise SystemExit("verify_dast_smoke: cross-tenant client visible in list response")
    finally:
        if client_a_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_a_id,))
        if client_b_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_b_id,))
        if listing_a_id:
            conn.execute("DELETE FROM listings WHERE id = %s", (listing_a_id,))
        if listing_b_id:
            conn.execute("DELETE FROM listings WHERE id = %s", (listing_b_id,))
        if user_a_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s", (user_a_id,)
            )
            conn.execute("DELETE FROM auth_security_events WHERE user_id = %s", (user_a_id,))
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_a_id,))
        if user_b_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s", (user_b_id,)
            )
            conn.execute("DELETE FROM auth_security_events WHERE user_id = %s", (user_b_id,))
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_b_id,))
        if agency_a_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_a_id,))
            conn.execute("DELETE FROM auth_security_events WHERE agency_id = %s", (agency_a_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_a_id,))
        if agency_b_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_b_id,))
            conn.execute("DELETE FROM auth_security_events WHERE agency_id = %s", (agency_b_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_b_id,))
        conn.commit()
        conn.close()


def main() -> None:
    _bootstrap()
    from django.test import Client

    logging.getLogger("log").setLevel(logging.ERROR)
    logging.getLogger("django.request").setLevel(logging.ERROR)

    client = Client()
    _run_unauthenticated_smoke(client)
    _run_authenticated_security_smoke(client)
    print("verify_dast_smoke: OK")


if __name__ == "__main__":
    main()
