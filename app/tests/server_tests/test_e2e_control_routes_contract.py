from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
    token_for,
)

ensure_django()

from server.pg.schema import ensure_schema  # noqa: E402
from server.services import e2e_control  # noqa: E402

PASSWORD = "StrongTestPass_123!"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _route_case(route_template: str) -> tuple[str, str, dict[str, object]]:
    if route_template in {"e2e/runtime/identity/", "e2e/entities/inspect/"}:
        return "get", f"/api/v1/{route_template}", {}
    payload: dict[str, object] = {}
    if route_template == "e2e/notifications/publish/":
        payload = {"title": "disabled", "body": "disabled"}
    elif route_template == "e2e/imports/pause-next/":
        payload = {"seconds": 1}
    elif route_template == "e2e/faults/inject/":
        payload = {"route_template": "clients/", "status_code": 503}
    elif route_template == "e2e/auth/revoke-session/":
        payload = {"session_id": "disabled"}
    return "post", f"/api/v1/{route_template}", payload


E2E_ROUTE_CASES = tuple(_route_case(route) for route in e2e_control.REQUIRED_E2E_ROUTE_TEMPLATES)


def test_e2e_control_routes_do_not_add_product_mutation_backdoors() -> None:
    route_text = "\n".join(e2e_control.REQUIRED_E2E_ROUTE_TEMPLATES).lower()
    assert not re.search(r"e2e/.*/(?:demandes|offers|matches?)(?:/|$)", route_text)
    assert not re.search(r"(create|update|delete|restore|purge).*(demande|offer|match)", route_text)


def test_offer_side_match_e2e_remains_nightly_without_sleep_or_skip() -> None:
    source = (
        REPO_ROOT / "app" / "tests" / "e2e_desktop" / "test_match_rebuild_journeys.py"
    ).read_text(encoding="utf-8")
    assert "def test_offer_mutation_rebuilds_match_results_via_desktop_ui" in source
    assert "pytest.mark.e2e_nightly" in source
    banned = ("time.sleep", "pytest.skip", "pytest.xfail", "mark.skip", "mark.xfail")
    assert not [needle for needle in banned if needle in source]


def test_crud_e2e_does_not_hide_failures_with_sleep_skip_or_xfail() -> None:
    source = (REPO_ROOT / "app" / "tests" / "e2e_desktop" / "test_demande_offer_crud.py").read_text(
        encoding="utf-8"
    )
    banned = ("time.sleep", "pytest.skip", "pytest.xfail", "mark.skip", "mark.xfail")
    assert not [needle for needle in banned if needle in source]


def test_deactivated_user_e2e_asserts_specific_auth_session_contract() -> None:
    journey_source = (REPO_ROOT / "app" / "tests" / "e2e_desktop" / "test_journeys.py").read_text(
        encoding="utf-8"
    )
    page_source = (REPO_ROOT / "app" / "tests" / "e2e_desktop" / "pages.py").read_text(
        encoding="utf-8"
    )

    assert "def test_deactivated_user_cannot_mutate_on_next_protected_action" in journey_source
    assert "create_client_expect_auth_error" in journey_source
    assert "assert error_text" not in journey_source
    assert "create_client_expect_error" not in page_source
    assert "clientsAuthRequiredMessageBox" in page_source
    assert "Session needs attention" in page_source


def test_e2e_backend_identity_covers_product_backend_source() -> None:
    identity_files = set(e2e_control.iter_product_identity_files(REPO_ROOT))
    assert len(identity_files) > 100
    assert "server/services/e2e_control.py" in identity_files
    assert "server/services/demandes.py" in identity_files
    assert "server/services/offers.py" in identity_files
    assert "server/services/matches.py" in identity_files
    assert "core/data/match_cache_write.py" in identity_files
    assert "core/contracts/route_policy_registry.py" in identity_files
    assert "requirements/server.txt" in identity_files


def test_e2e_product_identity_is_non_empty_and_build_stamped(tmp_path: Path) -> None:
    product_identity = e2e_control.build_product_identity(REPO_ROOT)
    assert product_identity["identity_kind"] == "e2e_product_source"
    assert product_identity["code_identity"]["fingerprint_scope"] == "e2e_product_source"
    fingerprint = product_identity["code_identity"]["source_fingerprint"]
    assert isinstance(fingerprint, str)
    assert len(fingerprint) == 64
    file_count = product_identity["server_files_fingerprint"]["file_count"]
    assert isinstance(file_count, int)
    assert file_count > 100

    output_path = tmp_path / e2e_control.E2E_BUILD_IDENTITY_FILE
    written_path = e2e_control.write_build_identity(REPO_ROOT, output_path=output_path)
    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert payload["code_identity"]["source_fingerprint"] == fingerprint


def _make_user(prefix: str) -> tuple[int, int, object, str]:
    ensure_schema()
    conn = admin_conn()
    try:
        suffix = uuid.uuid4().hex[:8]
        agency_id = create_agency(conn, f"{prefix}{suffix}", f"{prefix} Agency")
        username = f"{prefix.lower()}_{suffix}"
        user_id = create_manager_user(
            conn, agency_id=agency_id, username=username, password=PASSWORD
        )
        conn.commit()
    finally:
        conn.close()
    user = get_user_model().objects.get(id=user_id)
    return int(agency_id), int(user_id), user, username


def _auth_headers(username: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token_for(username, PASSWORD)}"}


def _cleanup_user(*, agency_id: int, user_id: int) -> None:
    conn = admin_conn()
    try:
        conn.execute("DELETE FROM match_counts_cache WHERE agency_id = %s", (agency_id,))
        conn.commit()
    finally:
        conn.close()
    cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def _post_json(
    client: Client,
    path: str,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
):
    return client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_HOST="localhost",
        **(headers or {}),
    )


def _assert_no_secret_terms(value: Any) -> None:
    banned = ("password", "secret", "token", "authorization", "bearer")
    if isinstance(value, dict):
        for key, nested in value.items():
            assert not any(term in str(key).lower() for term in banned)
            _assert_no_secret_terms(nested)
    elif isinstance(value, list):
        for item in value:
            _assert_no_secret_terms(item)
    elif isinstance(value, str):
        lowered = value.lower()
        assert not any(term in lowered for term in banned)


@pytest.mark.parametrize(("method", "path", "payload"), E2E_ROUTE_CASES)
def test_e2e_routes_return_404_before_auth_when_mode_disabled(
    monkeypatch,
    method: str,
    path: str,
    payload: dict[str, object],
) -> None:
    monkeypatch.delenv("IMMOAPP_E2E_TEST_MODE", raising=False)
    client = Client()
    if method == "get":
        response = client.get(path, HTTP_HOST="localhost")
    else:
        response = _post_json(client, path, payload)
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path", "payload"), E2E_ROUTE_CASES)
def test_e2e_routes_return_404_for_authenticated_requests_when_mode_disabled(
    monkeypatch,
    method: str,
    path: str,
    payload: dict[str, object],
) -> None:
    monkeypatch.delenv("IMMOAPP_E2E_TEST_MODE", raising=False)
    agency_id, user_id, _user, username = _make_user("E2EDIS")
    try:
        client = Client()
        if method == "get":
            response = client.get(path, HTTP_HOST="localhost", **_auth_headers(username))
        else:
            response = _post_json(client, path, payload, _auth_headers(username))
        assert response.status_code == 404
    finally:
        _cleanup_user(agency_id=agency_id, user_id=user_id)


def test_e2e_identity_route_returns_expected_shape_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "1")
    agency_id, user_id, _user, username = _make_user("E2EID")
    try:
        response = Client().get(
            "/api/v1/e2e/runtime/identity/",
            HTTP_HOST="localhost",
            **_auth_headers(username),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["e2e_test_mode"] is True
        assert isinstance(payload["backend_pid"], int)
        assert payload["runtime_source_mode"] in {
            "bind_mount",
            "image",
            "unknown",
        }
        assert isinstance(payload["code_identity"]["source_fingerprint"], str)
        assert isinstance(payload["server_files_fingerprint"]["aggregate_sha256"], str)
        build_identity = payload["build_identity"]
        if build_identity is not None:
            assert build_identity["identity_kind"] == "e2e_product_source"
            assert isinstance(build_identity["code_identity"]["source_fingerprint"], str)
        route_presence = payload["route_presence"]
        for route_template in e2e_control.REQUIRED_E2E_ROUTE_TEMPLATES:
            assert route_presence[route_template] is True
    finally:
        _cleanup_user(agency_id=agency_id, user_id=user_id)


def test_e2e_identity_route_does_not_expose_secret_terms(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "1")
    agency_id, user_id, _user, username = _make_user("E2ESEC")
    try:
        response = Client().get(
            "/api/v1/e2e/runtime/identity/",
            HTTP_HOST="localhost",
            **_auth_headers(username),
        )
        assert response.status_code == 200
        _assert_no_secret_terms(response.json())
    finally:
        _cleanup_user(agency_id=agency_id, user_id=user_id)


def test_e2e_inspect_route_requires_auth(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "1")
    response = Client().get(
        "/api/v1/e2e/entities/inspect/?entity_type=client&phone=0555000000",
        HTTP_HOST="localhost",
    )
    assert response.status_code in {401, 403}


def test_e2e_notification_publish_route_requires_auth(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "1")
    response = _post_json(
        Client(),
        "/api/v1/e2e/notifications/publish/",
        {"title": "No auth", "body": "No auth"},
    )
    assert response.status_code in {401, 403}


def test_e2e_fault_injection_rejects_unknown_route_template(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "1")
    agency_id, user_id, _user, username = _make_user("E2EFAULT")
    try:
        response = _post_json(
            Client(),
            "/api/v1/e2e/faults/inject/",
            {"route_template": "does/not/exist/", "status_code": 503},
            _auth_headers(username),
        )
        assert response.status_code == 400
        assert "registered API route" in response.json()["detail"]
    finally:
        _cleanup_user(agency_id=agency_id, user_id=user_id)
