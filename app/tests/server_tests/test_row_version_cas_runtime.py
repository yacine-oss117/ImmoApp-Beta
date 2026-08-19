from __future__ import annotations

import json
import uuid

import pytest
from django.test import Client

pytest.importorskip("psycopg", reason="row-version CAS runtime tests require server dependencies")

from app.tests.server_tests._integration_auth_helpers import (  # noqa: E402
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
    token_for,
)


def test_client_update_rejects_stale_row_version_and_preserves_server_record() -> None:
    ensure_django()
    suffix = uuid.uuid4().hex[:8]
    username = f"cas_mgr_{suffix}"
    password = "StrongTestPass_123!"
    phone_digits = str(int(suffix, 16))[-6:].rjust(6, "0")

    agency_id = 0
    user_id = 0
    client_id = 0

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"CAS{suffix}", f"CAS Agency {suffix}")
        user_id = create_manager_user(
            conn, agency_id=agency_id, username=username, password=password
        )
        conn.commit()

        token = token_for(username, password)
        web = Client()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        create = web.post(
            "/api/v1/clients/",
            data=json.dumps({"family_name": f"CAS User {suffix}", "phone": f"21388{phone_digits}"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_IDEMPOTENCY_KEY=f"cas-create-{suffix}",
            **auth,
        )
        assert create.status_code == 201, create.content.decode("utf-8", errors="ignore")
        client_id = int(create.json()["id"])

        detail = web.get(f"/api/v1/clients/{client_id}/", HTTP_HOST="localhost", **auth)
        assert detail.status_code == 200
        detail_payload = detail.json()
        row_version = int(detail_payload.get("row_version", 1))

        # Correct CAS update succeeds.
        update_ok = web.put(
            f"/api/v1/clients/{client_id}/",
            data=json.dumps({"family_name": f"CAS Updated {suffix}", "row_version": row_version}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_IDEMPOTENCY_KEY=f"cas-ok-{suffix}",
            **auth,
        )
        assert update_ok.status_code == 200, update_ok.content.decode("utf-8", errors="ignore")
        fresh_after_ok = web.get(f"/api/v1/clients/{client_id}/", HTTP_HOST="localhost", **auth)
        assert fresh_after_ok.status_code == 200
        after_ok_payload = fresh_after_ok.json()
        updated_row_version = int(after_ok_payload.get("row_version", row_version + 1))
        assert updated_row_version > row_version

        # Reusing stale row_version must fail with 409 and include current version data.
        update_stale = web.put(
            f"/api/v1/clients/{client_id}/",
            data=json.dumps({"family_name": f"CAS Stale {suffix}", "row_version": row_version}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_IDEMPOTENCY_KEY=f"cas-stale-{suffix}",
            **auth,
        )
        assert update_stale.status_code == 409
        stale_body = update_stale.json()
        assert "detail" in stale_body
        errors = stale_body.get("errors")
        assert isinstance(errors, dict)
        assert errors.get("current_row_version") is not None
        current_record = errors.get("current_record")
        assert isinstance(current_record, dict)
        assert current_record.get("family_name") == f"CAS Updated {suffix}"

        fresh_after_stale = web.get(f"/api/v1/clients/{client_id}/", HTTP_HOST="localhost", **auth)
        assert fresh_after_stale.status_code == 200
        after_stale_payload = fresh_after_stale.json()
        assert str(after_stale_payload.get("family_name")) == f"CAS Updated {suffix}"
        assert int(after_stale_payload.get("row_version", 0)) == updated_row_version
    finally:
        conn.rollback()
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)
