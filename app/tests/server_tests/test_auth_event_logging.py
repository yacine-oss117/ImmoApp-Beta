from __future__ import annotations

import json
import uuid

from django.test import Client

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
    token_for,
)


def test_login_attempts_emit_auth_security_events() -> None:
    ensure_django()
    suffix = uuid.uuid4().hex[:8]
    username = f"auth_evt_{suffix}"
    password = "StrongAuthEventPass_123!"
    code = f"AUTH{suffix}"
    marker = f"AUTH_EVT_{suffix}"

    agency_id = 0
    user_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, code, f"Auth Event Agency {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=username,
            password=password,
        )
        conn.commit()

        web = Client()
        bad = web.post(
            "/api/auth/token/",
            data=json.dumps({"username": username, "password": f"{password}_wrong"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_USER_AGENT=marker,
            REMOTE_ADDR="10.12.0.50",
            HTTP_X_REQUEST_ID=f"rid-fail-{suffix}",
        )
        assert bad.status_code == 401

        ok = web.post(
            "/api/auth/token/",
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_USER_AGENT=marker,
            REMOTE_ADDR="10.12.0.51",
            HTTP_X_REQUEST_ID=f"rid-ok-{suffix}",
        )
        assert ok.status_code == 200

        rows = conn.execute(
            """
            SELECT event_type, outcome, identifier, user_id, agency_id, reason_code, source_ip
            FROM auth_security_events
            WHERE identifier = %s
            ORDER BY id DESC
            LIMIT 10
            """,
            (username,),
        ).fetchall()
        events = [(row["event_type"], row["outcome"], row["reason_code"]) for row in rows]
        assert ("login_failed", "failure", "invalid_credentials") in events
        assert ("login_success", "success", "token_issued") in events
        assert any(
            row["user_id"] == user_id and row["agency_id"] == agency_id for row in rows
        ), "auth event rows should include resolved user and agency"
        assert any(
            str(row.get("source_ip") or "").startswith("10.12.0.") for row in rows
        ), "auth event rows should include source IP"
    finally:
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def test_auth_security_events_endpoint_is_available_for_manager() -> None:
    ensure_django()
    suffix = uuid.uuid4().hex[:8]
    username = f"auth_evt_view_{suffix}"
    password = "StrongAuthEventViewPass_123!"
    code = f"AUTHV{suffix}"
    agency_id = 0
    user_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, code, f"Auth Event View Agency {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=username,
            password=password,
        )
        conn.execute(
            """
            INSERT INTO auth_security_events (
                agency_id, user_id, event_type, outcome, identifier, reason_code
            )
            VALUES (%s, %s, 'login_failed', 'failure', %s, 'manual_test')
            """,
            (agency_id, user_id, username),
        )
        conn.commit()

        token = token_for(username, password)
        web = Client()
        response = web.get(
            "/api/v1/audit/auth-events/",
            {"event_type": "login_failed", "limit": 20},
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 200, response.content.decode("utf-8", errors="ignore")
        payload = response.json()
        assert isinstance(payload.get("items"), list)
        assert payload.get("total", 0) >= 1
        assert any(item.get("event_type") == "login_failed" for item in payload["items"])
    finally:
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def test_refresh_failure_emits_auth_event() -> None:
    ensure_django()
    suffix = uuid.uuid4().hex[:8]
    username = f"auth_evt_refresh_{suffix}"
    password = "StrongRefreshFailPass_123!"
    code = f"AUTHR{suffix}"
    agency_id = 0
    user_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, code, f"Auth Refresh Agency {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=username,
            password=password,
        )
        conn.commit()

        web = Client()
        bad_refresh = web.post(
            "/api/auth/token/refresh/",
            data=json.dumps({"refresh": "invalid-refresh-token"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_REQUEST_ID=f"rid-refresh-{suffix}",
        )
        assert bad_refresh.status_code in (401, 403)

        rows = conn.execute("""
            SELECT event_type, outcome, reason_code
            FROM auth_security_events
            WHERE event_type = 'token_refresh_failed'
            ORDER BY id DESC
            LIMIT 5
            """).fetchall()
        assert rows, "expected at least one token_refresh_failed auth event"
        assert any(
            row["outcome"] == "failure" and row["reason_code"] == "invalid_refresh_token"
            for row in rows
        )
    finally:
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)
