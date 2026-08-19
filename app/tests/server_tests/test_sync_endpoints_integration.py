from __future__ import annotations

import json
import uuid

import pytest
from django.test import Client

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
    token_for,
)
from server.pg.schema import ensure_schema

ensure_django()

pytestmark = pytest.mark.integration


def _create_client_via_api(web: Client, *, token: str, family_name: str, phone: str) -> int:
    response = web.post(
        "/api/v1/clients/",
        data=json.dumps({"family_name": family_name, "phone": phone}),
        content_type="application/json",
        HTTP_HOST="localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 201, response.content.decode("utf-8", errors="ignore")
    payload = response.json()
    return int(payload["id"])


def _get_changes(
    web: Client,
    *,
    token: str | None,
    since: str,
    limit: int = 1000,
    after_id: object | None = None,
):
    kwargs: dict[str, object] = {"HTTP_HOST": "localhost"}
    if token:
        kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    params: dict[str, object] = {"since": since, "limit": limit}
    if after_id is not None:
        params["after_id"] = after_id
    return web.get("/api/v1/clients/changes/", data=params, **kwargs)


def test_clients_changes_enforces_tenant_since_and_cursor_contract() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    digits = ("".join(ch for ch in suffix if ch.isdigit()) + "012345")[:6]
    username_a = f"sync_a_{suffix}"
    username_b = f"sync_b_{suffix}"
    password = "StrongTestPass_123!"

    agency_a_id = 0
    agency_b_id = 0
    user_a_id = 0
    user_b_id = 0
    client_a1_id = 0
    client_a2_id = 0
    client_b_id = 0

    web = Client()
    conn = admin_conn()
    try:
        agency_a_id = create_agency(conn, f"SYNCA{suffix}", f"Sync Agency A {suffix}")
        agency_b_id = create_agency(conn, f"SYNCB{suffix}", f"Sync Agency B {suffix}")
        user_a_id = create_manager_user(
            conn, agency_id=agency_a_id, username=username_a, password=password
        )
        user_b_id = create_manager_user(
            conn, agency_id=agency_b_id, username=username_b, password=password
        )
        conn.commit()

        token_a = token_for(username_a, password)
        token_b = token_for(username_b, password)
        client_a1_id = _create_client_via_api(
            web,
            token=token_a,
            family_name=f"SYNC_A1_{suffix}",
            phone=f"+213557{digits}",
        )
        client_a2_id = _create_client_via_api(
            web,
            token=token_a,
            family_name=f"SYNC_A2_{suffix}",
            phone=f"+213668{digits}",
        )
        client_b_id = _create_client_via_api(
            web,
            token=token_b,
            family_name=f"SYNC_B_{suffix}",
            phone=f"+213779{digits}",
        )

        first = _get_changes(
            web,
            token=token_a,
            since="1970-01-01T00:00:00+00:00",
            limit=1,
        )
        assert first.status_code == 200, first.content.decode("utf-8", errors="ignore")
        first_payload = first.json()
        first_items = first_payload.get("items", [])
        assert isinstance(first_items, list)
        assert first_items, "Expected at least one client in first sync page"
        first_ids = {
            int(item["id"]) for item in first_items if isinstance(item, dict) and "id" in item
        }
        assert client_b_id not in first_ids
        assert first_payload.get("next_since")
        assert first_payload.get("next_after_id") is not None

        second = _get_changes(
            web,
            token=token_a,
            since=str(first_payload["next_since"]),
            limit=1000,
            after_id=int(first_payload["next_after_id"]),
        )
        assert second.status_code == 200, second.content.decode("utf-8", errors="ignore")
        second_payload = second.json()
        second_items = second_payload.get("items", [])
        assert isinstance(second_items, list)
        second_ids = {
            int(item["id"]) for item in second_items if isinstance(item, dict) and "id" in item
        }
        assert client_b_id not in second_ids
        assert first_ids.isdisjoint(second_ids)
        assert second_ids.issubset({client_a1_id, client_a2_id})
    finally:
        conn.rollback()
        conn.close()
        if agency_a_id:
            cleanup_import_test_agency(agency_id=agency_a_id, user_id=user_a_id)
        if agency_b_id:
            cleanup_import_test_agency(agency_id=agency_b_id, user_id=user_b_id)


def test_clients_changes_requires_authentication() -> None:
    ensure_schema()
    web = Client()
    response = _get_changes(
        web,
        token=None,
        since="1970-01-01T00:00:00+00:00",
        limit=1,
    )
    assert response.status_code == 401


def test_clients_changes_rejects_invalid_after_id() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    username = f"sync_cursor_{suffix}"
    password = "StrongTestPass_123!"
    agency_id = 0
    user_id = 0

    web = Client()
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"SYNCC{suffix}", f"Sync Cursor Agency {suffix}")
        user_id = create_manager_user(
            conn, agency_id=agency_id, username=username, password=password
        )
        conn.commit()

        token = token_for(username, password)
        response_bad = _get_changes(
            web,
            token=token,
            since="1970-01-01T00:00:00+00:00",
            after_id="abc",
        )
        assert response_bad.status_code == 400, response_bad.content.decode(
            "utf-8", errors="ignore"
        )

        response_negative = _get_changes(
            web,
            token=token,
            since="1970-01-01T00:00:00+00:00",
            after_id=-1,
        )
        assert response_negative.status_code == 400, response_negative.content.decode(
            "utf-8", errors="ignore"
        )
    finally:
        conn.rollback()
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)
