"""
OIDC authentication views.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Mapping
from typing import Any

from django.contrib.auth.hashers import check_password, make_password
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.logging_config import get_correlation_id
from server.services import auth_events, oidc_auth

_MIN_AUTH_SECONDS = 0.2
_DUMMY_HASH = make_password("invalid-password")


def _sleep_to_min(start: float, minimum: float) -> None:
    elapsed = time.monotonic() - start
    if elapsed >= minimum:
        return
    jitter_ms = secrets.randbelow(41) + 10  # 10-50ms
    time.sleep(minimum - elapsed + (jitter_ms / 1000))


def _extract_text(payload: object, key: str) -> str:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _client_ip(request: Request) -> str | None:
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", "") or "")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[0]
    remote = str(request.META.get("REMOTE_ADDR", "") or "").strip()
    return remote or None


def _log_auth_event(
    *,
    event_type: str,
    outcome: str,
    request: Request,
    user_id: int | None,
    agency_id: int | None,
    identifier: str | None,
    reason_code: str,
    details: dict[str, Any] | None = None,
) -> None:
    auth_events.log_auth_event(
        event_type=event_type,
        outcome=outcome,
        user_id=user_id,
        agency_id=agency_id,
        identifier=identifier,
        reason_code=reason_code,
        source_ip=_client_ip(request),
        user_agent=str(request.META.get("HTTP_USER_AGENT", "") or "")[:512] or None,
        request_id=get_correlation_id(),
        details=details or {"path": request.path, "method": request.method},
        fail_silently=True,
    )


class OidcConfigView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "token_oidc"
    throttle_classes = [ScopedRateThrottle]

    def get(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        payload = oidc_auth.oidc_public_config()
        return Response(payload, status=200)


class OidcTokenView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "token_oidc"
    throttle_classes = [ScopedRateThrottle]

    def post(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        start = time.monotonic()
        id_token = _extract_text(request.data, "id_token")
        nonce = _extract_text(request.data, "nonce") or None

        _log_auth_event(
            event_type="oidc_login_attempt",
            outcome="attempt",
            request=request,
            user_id=None,
            agency_id=None,
            identifier=None,
            reason_code="submitted",
            details={"path": request.path, "method": request.method, "oidc": True},
        )

        try:
            result = oidc_auth.authenticate_oidc_token(id_token, nonce=nonce)
        except oidc_auth.OidcAuthError as exc:
            check_password("constant-time", _DUMMY_HASH)
            _log_auth_event(
                event_type="oidc_login_failed",
                outcome="failure",
                request=request,
                user_id=None,
                agency_id=None,
                identifier=None,
                reason_code="oidc_verification_failed",
                details={
                    "path": request.path,
                    "method": request.method,
                    "oidc": True,
                    "error": str(exc),
                },
            )
            _sleep_to_min(start, _MIN_AUTH_SECONDS)
            raise AuthenticationFailed("Invalid credentials") from exc

        check_password("constant-time", _DUMMY_HASH)
        _log_auth_event(
            event_type="oidc_login_success",
            outcome="success",
            request=request,
            user_id=result.get("user_id"),
            agency_id=result.get("agency_id"),
            identifier=result.get("identifier"),
            reason_code="token_issued",
            details={
                "path": request.path,
                "method": request.method,
                "oidc": True,
                "subject": result.get("subject"),
            },
        )
        _sleep_to_min(start, _MIN_AUTH_SECONDS)
        return Response({"access": result["access"], "refresh": result["refresh"]}, status=200)


__all__ = ["OidcConfigView", "OidcTokenView"]
