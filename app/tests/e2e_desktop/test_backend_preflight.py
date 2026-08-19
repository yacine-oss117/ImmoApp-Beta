from __future__ import annotations

import json
from typing import Any

import pytest
from requests import Response

from app.tests.e2e_desktop import backend
from server.services import e2e_control

EXPECTED_IDENTITY = {
    "git_sha": None,
    "dirty": None,
    "source_fingerprint": "expected-fingerprint",
    "identity_kind": "fingerprint",
}


def _response(status_code: int, payload: dict[str, Any] | None = None, text: str = "") -> Response:
    response = Response()
    response.status_code = status_code
    response._content = (json.dumps(payload if payload is not None else {"detail": text})).encode(
        "utf-8"
    )
    response.headers["content-type"] = "application/json"
    return response


def _identity_payload(
    *,
    fingerprint: str = "expected-fingerprint",
    build_fingerprint: str | None = "expected-fingerprint",
    route_presence: dict[str, bool] | None = None,
    e2e_test_mode: bool = True,
    runtime_source_mode: str = "image",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "e2e_test_mode": e2e_test_mode,
        "backend_pid": 123,
        "process_start_time": 123.0,
        "runtime_source_mode": runtime_source_mode,
        "app_root": "/app",
        "code_identity": {
            "git_sha": None,
            "dirty": None,
            "source_fingerprint": fingerprint,
            "identity_kind": "fingerprint",
        },
        "server_files_fingerprint": {"aggregate_sha256": fingerprint, "files": {}},
        "route_presence": (
            route_presence
            if route_presence is not None
            else {route: True for route in e2e_control.REQUIRED_E2E_ROUTE_TEMPLATES}
        ),
    }
    if build_fingerprint is not None:
        payload["build_identity"] = {
            "identity_kind": "e2e_product_source",
            "code_identity": {
                "git_sha": None,
                "dirty": None,
                "source_fingerprint": build_fingerprint,
                "identity_kind": "fingerprint",
                "fingerprint_scope": "e2e_product_source",
            },
            "server_files_fingerprint": {
                "aggregate_sha256": build_fingerprint,
                "file_count": 1,
            },
        }
    return payload


def _patch_common_preflight(monkeypatch: pytest.MonkeyPatch, identity_response: Response) -> None:
    monkeypatch.setattr(backend, "expected_checkout_code_identity", lambda: dict(EXPECTED_IDENTITY))
    monkeypatch.setattr(
        backend.requests, "get", lambda *args, **kwargs: _response(200, {"ok": True})
    )
    monkeypatch.setattr(
        backend.requests, "post", lambda *args, **kwargs: _response(401, {"detail": "bad"})
    )
    monkeypatch.setattr(
        backend,
        "create_desktop_user",
        lambda **kwargs: backend.DesktopUser(agency_id=1, user_id=2, username="u", password="p"),
    )
    monkeypatch.setattr(backend, "cleanup_desktop_user", lambda user: None)
    monkeypatch.setattr(backend, "auth_token", lambda base_url, user: "token")
    monkeypatch.setattr(backend.requests, "request", lambda *args, **kwargs: identity_response)


def test_ensure_backend_ready_fails_fast_when_identity_endpoint_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_preflight(monkeypatch, _response(404, {"detail": "Not found"}))

    with pytest.raises(RuntimeError, match="disabled or the running backend is stale") as exc_info:
        backend.ensure_backend_ready("http://127.0.0.1:8000")

    assert "e2e/runtime/identity/" in str(exc_info.value)
    assert "Rebuild/restart the Docker backend" in str(exc_info.value)


def test_ensure_backend_ready_fails_fast_when_required_routes_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_presence = {route: True for route in e2e_control.REQUIRED_E2E_ROUTE_TEMPLATES}
    route_presence["e2e/entities/inspect/"] = False
    _patch_common_preflight(
        monkeypatch, _response(200, _identity_payload(route_presence=route_presence))
    )

    with pytest.raises(RuntimeError, match="Required E2E routes are missing") as exc_info:
        backend.ensure_backend_ready("http://127.0.0.1:8000")

    assert "e2e/entities/inspect/" in str(exc_info.value)


def test_ensure_backend_ready_fails_fast_on_code_fingerprint_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_preflight(
        monkeypatch,
        _response(200, _identity_payload(fingerprint="stale-fingerprint")),
    )

    with pytest.raises(RuntimeError, match="code identity does not match") as exc_info:
        backend.ensure_backend_ready("http://127.0.0.1:8000")

    assert "expected-fingerprint" in str(exc_info.value)
    assert "stale-fingerprint" in str(exc_info.value)


def test_ensure_backend_ready_fails_fast_when_image_build_identity_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_preflight(
        monkeypatch,
        _response(200, _identity_payload(build_fingerprint=None)),
    )

    with pytest.raises(RuntimeError, match="image build identity is missing") as exc_info:
        backend.ensure_backend_ready("http://127.0.0.1:8000")

    assert "Actual image build fingerprint: <missing>" in str(exc_info.value)


def test_ensure_backend_ready_fails_fast_when_image_build_identity_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_preflight(
        monkeypatch,
        _response(200, _identity_payload(build_fingerprint="stale-build-fingerprint")),
    )

    with pytest.raises(RuntimeError, match="image build identity does not match") as exc_info:
        backend.ensure_backend_ready("http://127.0.0.1:8000")

    assert "stale-build-fingerprint" in str(exc_info.value)


def test_ensure_backend_ready_passes_when_identity_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common_preflight(monkeypatch, _response(200, _identity_payload()))

    result = backend.ensure_backend_ready("http://127.0.0.1:8000")

    assert result.identity_match is True
    assert result.missing_routes == ()
    assert result.actual_identity is not None


def test_ensure_backend_ready_rejects_synced_container_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_preflight(
        monkeypatch,
        _response(200, _identity_payload(runtime_source_mode="synced_container")),
    )

    with pytest.raises(RuntimeError, match="does not support copied-file container sync"):
        backend.ensure_backend_ready("http://127.0.0.1:8000")


def test_authed_request_uses_consistent_e2e_404_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, "auth_token", lambda base_url, user: "token")
    monkeypatch.setattr(backend.requests, "request", lambda *args, **kwargs: _response(404))

    with pytest.raises(RuntimeError, match="disabled or the running backend is stale") as exc_info:
        backend._authed_request(
            method="GET",
            base_url="http://127.0.0.1:8000",
            user=backend.DesktopUser(agency_id=1, user_id=2, username="u", password="p"),
            path="e2e/entities/inspect",
        )

    assert "e2e/entities/inspect/" in str(exc_info.value)


def test_json_request_uses_consistent_e2e_404_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend.requests, "request", lambda *args, **kwargs: _response(404))

    with pytest.raises(RuntimeError, match="disabled or the running backend is stale") as exc_info:
        backend._json_request(
            method="GET",
            url="http://127.0.0.1:8000/api/v1/e2e/runtime/identity/",
            token="token",
        )

    assert "e2e/runtime/identity/" in str(exc_info.value)
