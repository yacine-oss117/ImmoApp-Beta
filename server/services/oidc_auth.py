"""
OIDC identity-token validation and local JWT issuance.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt


class OidcAuthError(RuntimeError):
    """Raised when OIDC login/verification fails."""


@dataclass(frozen=True)
class OidcConfig:
    enabled: bool
    issuer: str
    discovery_url: str
    jwks_uri: str
    client_id: str
    audiences: tuple[str, ...]
    username_claims: tuple[str, ...]
    email_claim: str
    verify_ssl: bool
    timeout_seconds: float
    cache_ttl_seconds: int


_DISCOVERY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _ssl_context(verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _get_user_model() -> Any:
    from django.contrib.auth import get_user_model

    return get_user_model()


def _new_refresh_token(user: Any) -> Any:
    from rest_framework_simplejwt.tokens import RefreshToken

    return RefreshToken.for_user(user)


def _http_get_json(url: str, *, timeout: float, verify_ssl: bool) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(
            req, timeout=timeout, context=_ssl_context(verify_ssl)
        ) as response:
            payload = response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise OidcAuthError(f"OIDC HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OidcAuthError(f"OIDC connection failed: {exc}") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OidcAuthError("OIDC endpoint returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise OidcAuthError("OIDC endpoint returned invalid JSON payload.")
    return data


def _cache_get_or_set(
    cache: dict[str, tuple[float, dict[str, Any]]],
    key: str,
    *,
    ttl_seconds: int,
    loader: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    now = time.monotonic()
    current = cache.get(key)
    if current and current[0] > now:
        return current[1]
    value = loader()
    cache[key] = (now + max(ttl_seconds, 10), value)
    return value


def _required_when_enabled(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise OidcAuthError(f"{name} is required when OIDC_ENABLED=1.")
    return text


def get_oidc_config() -> OidcConfig:
    enabled = _truthy(os.environ.get("OIDC_ENABLED", "0"))
    issuer = (os.environ.get("OIDC_ISSUER") or "").strip()
    discovery_url = (os.environ.get("OIDC_DISCOVERY_URL") or "").strip()
    jwks_uri = (os.environ.get("OIDC_JWKS_URI") or "").strip()
    client_id = (os.environ.get("OIDC_CLIENT_ID") or "").strip()

    if enabled:
        issuer = _required_when_enabled("OIDC_ISSUER", issuer)
        client_id = _required_when_enabled("OIDC_CLIENT_ID", client_id)
    elif not issuer:
        issuer = "https://example.invalid"
    if not discovery_url:
        discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    if not jwks_uri:
        jwks_uri = ""

    audiences = _split_csv(os.environ.get("OIDC_AUDIENCES"))
    if not audiences and client_id:
        audiences = (client_id,)

    username_claims = _split_csv(
        os.environ.get("OIDC_USERNAME_CLAIMS", "preferred_username,email,sub")
    )
    if not username_claims:
        username_claims = ("preferred_username", "email", "sub")

    return OidcConfig(
        enabled=enabled,
        issuer=issuer.rstrip("/"),
        discovery_url=discovery_url,
        jwks_uri=jwks_uri,
        client_id=client_id,
        audiences=audiences,
        username_claims=username_claims,
        email_claim=(os.environ.get("OIDC_EMAIL_CLAIM") or "email").strip() or "email",
        verify_ssl=not _truthy(os.environ.get("OIDC_INSECURE_SKIP_VERIFY", "0")),
        timeout_seconds=float(os.environ.get("OIDC_TIMEOUT_SECONDS", "8")),
        cache_ttl_seconds=int(os.environ.get("OIDC_CACHE_TTL_SECONDS", "300")),
    )


def _discovery(cfg: OidcConfig) -> dict[str, Any]:
    return _cache_get_or_set(
        _DISCOVERY_CACHE,
        cfg.discovery_url,
        ttl_seconds=cfg.cache_ttl_seconds,
        loader=lambda: _http_get_json(
            cfg.discovery_url, timeout=cfg.timeout_seconds, verify_ssl=cfg.verify_ssl
        ),
    )


def _resolved_jwks_uri(cfg: OidcConfig) -> str:
    if cfg.jwks_uri:
        return cfg.jwks_uri
    metadata = _discovery(cfg)
    uri = str(metadata.get("jwks_uri") or "").strip()
    if not uri:
        raise OidcAuthError("OIDC discovery metadata does not contain jwks_uri.")
    return uri


def _jwks(cfg: OidcConfig) -> dict[str, Any]:
    uri = _resolved_jwks_uri(cfg)
    return _cache_get_or_set(
        _JWKS_CACHE,
        uri,
        ttl_seconds=cfg.cache_ttl_seconds,
        loader=lambda: _http_get_json(uri, timeout=cfg.timeout_seconds, verify_ssl=cfg.verify_ssl),
    )


def oidc_public_config() -> dict[str, Any]:
    cfg = get_oidc_config()
    payload: dict[str, Any] = {
        "enabled": cfg.enabled,
        "issuer": cfg.issuer,
        "client_id": cfg.client_id if cfg.enabled else "",
        "username_claims": list(cfg.username_claims),
    }
    if not cfg.enabled:
        return payload
    try:
        metadata = _discovery(cfg)
    except OidcAuthError:
        return payload
    payload.update(
        {
            "authorization_endpoint": str(metadata.get("authorization_endpoint") or ""),
            "token_endpoint": str(metadata.get("token_endpoint") or ""),
            "device_authorization_endpoint": str(
                metadata.get("device_authorization_endpoint") or ""
            ),
            "scopes_supported": metadata.get("scopes_supported") or [],
        }
    )
    return payload


def _signing_key_for_token(id_token: str, cfg: OidcConfig) -> Any:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.InvalidTokenError as exc:
        raise OidcAuthError("Invalid OIDC token header.") from exc

    kid = str(header.get("kid") or "").strip()
    alg = str(header.get("alg") or "").strip() or "RS256"
    keys = _jwks(cfg).get("keys")
    if not isinstance(keys, list) or not keys:
        raise OidcAuthError("OIDC JWKS key set is empty.")

    key_payload: dict[str, Any] | None = None
    if kid:
        for candidate in keys:
            if isinstance(candidate, dict) and str(candidate.get("kid") or "") == kid:
                key_payload = candidate
                break
        if key_payload is None:
            raise OidcAuthError("OIDC key id (kid) not found in JWKS.")
    else:
        for candidate in keys:
            if isinstance(candidate, dict) and str(candidate.get("alg") or "") in {"", alg}:
                key_payload = candidate
                break
        if key_payload is None:
            raise OidcAuthError("OIDC signing key not found in JWKS.")

    try:
        algorithm = jwt.algorithms.get_default_algorithms().get(alg)
        if algorithm is None:
            raise OidcAuthError(f"Unsupported OIDC signing algorithm: {alg}")
        key = algorithm.from_jwk(json.dumps(key_payload))
    except OidcAuthError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise OidcAuthError("Failed to parse OIDC signing key.") from exc
    return key, alg


def verify_id_token(id_token: str, *, nonce: str | None = None) -> dict[str, Any]:
    cfg = get_oidc_config()
    if not cfg.enabled:
        raise OidcAuthError("OIDC is disabled.")
    token = id_token.strip()
    if not token:
        raise OidcAuthError("id_token is required.")

    key, alg = _signing_key_for_token(token, cfg)
    decode_kwargs: dict[str, Any] = {
        "algorithms": [alg],
        "issuer": cfg.issuer,
        "options": {"require": ["exp", "iss"]},
    }
    if cfg.audiences:
        decode_kwargs["audience"] = list(cfg.audiences)

    try:
        claims = jwt.decode(token, key=key, **decode_kwargs)
    except jwt.InvalidTokenError as exc:
        raise OidcAuthError("OIDC token verification failed.") from exc

    if not isinstance(claims, dict):
        raise OidcAuthError("OIDC token payload is invalid.")
    if nonce is not None and str(claims.get("nonce") or "") != nonce:
        raise OidcAuthError("OIDC token nonce mismatch.")
    return claims


def _extract_identifier(claims: dict[str, Any], cfg: OidcConfig) -> str:
    for claim_name in cfg.username_claims:
        value = claims.get(claim_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise OidcAuthError("OIDC token does not contain a usable identity claim.")


def resolve_local_user(claims: dict[str, Any]) -> tuple[Any, str]:
    cfg = get_oidc_config()
    identifier = _extract_identifier(claims, cfg)
    User = _get_user_model()
    user = None

    email_claim_value = claims.get(cfg.email_claim)
    if isinstance(email_claim_value, str) and email_claim_value.strip():
        user = User.objects.filter(email__iexact=email_claim_value.strip()).first()

    if not user:
        user = User.objects.filter(username=identifier).first()
    if not user:
        raise OidcAuthError("No local user is mapped to this OIDC identity.")
    if not user.is_active:
        raise OidcAuthError("User is inactive.")
    return user, identifier


def issue_internal_tokens(user: Any) -> dict[str, str]:
    refresh = _new_refresh_token(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def authenticate_oidc_token(id_token: str, *, nonce: str | None = None) -> dict[str, Any]:
    claims = verify_id_token(id_token, nonce=nonce)
    user, identifier = resolve_local_user(claims)
    tokens = issue_internal_tokens(user)
    return {
        **tokens,
        "user_id": int(user.id),
        "agency_id": getattr(user, "agency_id", None),
        "identifier": identifier,
        "subject": str(claims.get("sub") or ""),
        "claims": claims,
    }


__all__ = [
    "OidcAuthError",
    "authenticate_oidc_token",
    "get_oidc_config",
    "issue_internal_tokens",
    "oidc_public_config",
    "resolve_local_user",
    "verify_id_token",
]
