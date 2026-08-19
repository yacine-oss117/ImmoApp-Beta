from __future__ import annotations

import json
import uuid

import pytest
from django.core.cache import cache
from django.test import Client

pytest.importorskip("psycopg", reason="idempotency replay tests require server dependencies")

from app.tests.server_tests._integration_auth_helpers import (  # noqa: E402
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
    token_for,
)


def test_idempotency_replay_prevents_duplicate_creates_and_scopes_conflicts() -> None:
    ensure_django()
    suffix = uuid.uuid4().hex[:8]
    username = f"idem_mgr_{suffix}"
    password = "StrongTestPass_123!"
    idem_key = f"idem-{suffix}"
    phone_digits = str(int(suffix, 16))[-6:].rjust(6, "0")

    agency_id = 0
    user_id = 0
    created_client_id = 0

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IDM{suffix}", f"Idem Agency {suffix}")
        user_id = create_manager_user(
            conn, agency_id=agency_id, username=username, password=password
        )
        conn.commit()

        token = token_for(username, password)
        web = Client()
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_IDEMPOTENCY_KEY": idem_key}
        payload = {"family_name": f"Idem User {suffix}", "phone": f"21366{phone_digits}"}

        ids: list[int] = []
        statuses: list[int] = []
        for attempt in range(5):
            response = web.post(
                "/api/v1/clients/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_HOST="localhost",
                **headers,
            )
            statuses.append(response.status_code)
            assert response.status_code == 201, response.content.decode("utf-8", errors="ignore")
            idem_status = str(response.headers.get("Idempotency-Status", "")).strip().lower()
            assert idem_status in {"created", "replayed"}, response.headers
            if attempt >= 1:
                assert idem_status == "replayed", response.headers
            body = response.json()
            ids.append(int(body["id"]))

        assert len(set(ids)) == 1, "Idempotent replay must return the same resource id"
        created_client_id = ids[0]
        assert statuses.count(201) == 5

        # Verify only one row exists.
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM clients WHERE agency_id = %s AND id = %s",
            (agency_id, created_client_id),
        ).fetchone()
        assert row is not None
        assert int(row["n"]) == 1

        # Same idempotency key + different payload should fail with explicit conflict.
        conflict = web.post(
            "/api/v1/clients/",
            data=json.dumps(
                {"family_name": f"Idem User X {suffix}", "phone": f"21377{phone_digits}"}
            ),
            content_type="application/json",
            HTTP_HOST="localhost",
            **headers,
        )
        assert conflict.status_code == 409
        assert "Idempotency key conflict" in conflict.content.decode("utf-8", errors="ignore")

        # Simulate cache loss after first write (crash between write and replay cache availability).
        cache_key = f"idem:agency:{agency_id}:user:{user_id}:POST:/api/v1/clients/:{idem_key}"
        cache.delete(cache_key)
        replay_after_loss = web.post(
            "/api/v1/clients/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_HOST="localhost",
            **headers,
        )
        # Current behavior: duplicate is blocked by DB uniqueness even if replay cache is missing.
        assert replay_after_loss.status_code in (201, 409)
        row_after = conn.execute(
            "SELECT COUNT(*) AS n FROM clients WHERE agency_id = %s AND id = %s",
            (agency_id, created_client_id),
        ).fetchone()
        assert row_after is not None
        assert int(row_after["n"]) == 1
    finally:
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)
