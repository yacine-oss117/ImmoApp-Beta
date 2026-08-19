from __future__ import annotations

import base64
import json

import app.services.offline_account_scope as scope_module


def _b64(data: dict[str, object]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _make_token(payload: dict[str, object]) -> str:
    header = _b64({"alg": "none", "typ": "JWT"})
    body = _b64(payload)
    return f"{header}.{body}."


def test_sync_account_scope_from_token_persists_identity(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.setattr(scope_module, "get_api_base_url", lambda: "http://test")

    token = _make_token(
        {
            "agency_id": 11,
            "user_id": 7,
            "role": "manager",
            "is_owner": True,
        }
    )

    scope = scope_module.sync_account_scope_from_token(token)
    reloaded = scope_module.get_active_account_scope()

    assert scope is not None
    assert scope.agency_id == 11
    assert scope.user_id == 7
    assert scope.role == "manager"
    assert scope.is_owner is True
    assert reloaded is not None
    assert reloaded.account_key == scope.account_key
    assert reloaded.role == "manager"
    assert reloaded.is_owner is True


def test_sync_account_scope_from_token_returns_none_without_required_claims(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.setattr(scope_module, "get_api_base_url", lambda: "http://test")

    token = _make_token({"sub": "7"})

    scope = scope_module.sync_account_scope_from_token(token)

    assert scope is None
    assert scope_module.get_active_account_scope() is None


def test_get_active_account_scope_does_not_trigger_network_login_by_default(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.setattr(scope_module, "get_api_base_url", lambda: "http://test")
    monkeypatch.setattr(scope_module, "peek_access_token", lambda: None)
    monkeypatch.setattr(
        scope_module,
        "get_access_token",
        lambda: (_ for _ in ()).throw(AssertionError("network login should not be attempted")),
    )

    assert scope_module.get_active_account_scope() is None
