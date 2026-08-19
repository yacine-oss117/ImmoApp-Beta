from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.services import oidc_auth


def test_get_oidc_config_requires_issuer_and_client_id_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OIDC_ENABLED", "1")
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    with pytest.raises(oidc_auth.OidcAuthError, match="OIDC_ISSUER"):
        oidc_auth.get_oidc_config()


def test_verify_id_token_rejects_nonce_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = oidc_auth.OidcConfig(
        enabled=True,
        issuer="https://issuer.example",
        discovery_url="https://issuer.example/.well-known/openid-configuration",
        jwks_uri="https://issuer.example/jwks",
        client_id="client-id",
        audiences=("client-id",),
        username_claims=("preferred_username", "email", "sub"),
        email_claim="email",
        verify_ssl=True,
        timeout_seconds=3,
        cache_ttl_seconds=60,
    )
    monkeypatch.setattr(oidc_auth, "get_oidc_config", lambda: cfg)
    monkeypatch.setattr(oidc_auth, "_signing_key_for_token", lambda _t, _c: ("key", "RS256"))
    monkeypatch.setattr(
        oidc_auth.jwt,
        "decode",
        lambda *_a, **_k: {"sub": "123", "iss": cfg.issuer, "exp": 9999999999, "nonce": "real"},
    )
    with pytest.raises(oidc_auth.OidcAuthError, match="nonce mismatch"):
        oidc_auth.verify_id_token("token", nonce="expected")


def test_resolve_local_user_uses_email_then_username(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = oidc_auth.OidcConfig(
        enabled=True,
        issuer="https://issuer.example",
        discovery_url="https://issuer.example/.well-known/openid-configuration",
        jwks_uri="https://issuer.example/jwks",
        client_id="client-id",
        audiences=("client-id",),
        username_claims=("preferred_username", "email", "sub"),
        email_claim="email",
        verify_ssl=True,
        timeout_seconds=3,
        cache_ttl_seconds=60,
    )
    monkeypatch.setattr(oidc_auth, "get_oidc_config", lambda: cfg)

    class _FilterResult:
        def __init__(self, value):
            self._value = value

        def first(self):
            return self._value

    user_obj = SimpleNamespace(id=9, is_active=True, agency_id=2)
    calls: list[dict[str, object]] = []

    class _Manager:
        def filter(self, **kwargs):
            calls.append(kwargs)
            if "email__iexact" in kwargs:
                return _FilterResult(None)
            if kwargs.get("username") == "hashmalim":
                return _FilterResult(user_obj)
            return _FilterResult(None)

    fake_user_model = SimpleNamespace(objects=_Manager())
    monkeypatch.setattr(oidc_auth, "_get_user_model", lambda: fake_user_model)

    user, identifier = oidc_auth.resolve_local_user(
        {"preferred_username": "hashmalim", "email": "hashmalim@example.com"}
    )
    assert user is user_obj
    assert identifier == "hashmalim"
    assert any("email__iexact" in call for call in calls)
    assert any(call.get("username") == "hashmalim" for call in calls)


def test_authenticate_oidc_token_returns_internal_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(id=7, agency_id=3)
    monkeypatch.setattr(
        oidc_auth, "verify_id_token", lambda _t, nonce=None: {"sub": "abc", "exp": 1}
    )
    monkeypatch.setattr(oidc_auth, "resolve_local_user", lambda _c: (user, "hashmalim"))
    monkeypatch.setattr(
        oidc_auth, "issue_internal_tokens", lambda _u: {"access": "a", "refresh": "r"}
    )

    result = oidc_auth.authenticate_oidc_token("token", nonce="n")
    assert result["access"] == "a"
    assert result["refresh"] == "r"
    assert result["user_id"] == 7
    assert result["agency_id"] == 3
    assert result["identifier"] == "hashmalim"


def test_issue_internal_tokens_uses_refresh_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Refresh:
        access_token = "acc"

        def __str__(self) -> str:
            return "ref"

    monkeypatch.setattr(oidc_auth, "_new_refresh_token", lambda _u: _Refresh())
    tokens = oidc_auth.issue_internal_tokens(object())
    assert tokens["access"] == "acc"
    assert tokens["refresh"] == "ref"
