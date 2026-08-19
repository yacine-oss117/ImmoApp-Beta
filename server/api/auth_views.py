"""
Custom auth views with constant messaging and timing normalization.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Mapping
from typing import Any, cast

from django.contrib.auth.hashers import check_password, make_password
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.logging_config import get_correlation_id
from server.services import auth_events, auth_lockout, auth_security_alerts

from .auth_session_jwt import (
    SessionAwareTokenObtainPairSerializer,
    SessionAwareTokenRefreshSerializer,
)

_MIN_AUTH_SECONDS = 0.2
_DUMMY_HASH = make_password("invalid-password")


def _sleep_to_min(start: float, minimum: float) -> None:
    elapsed = time.monotonic() - start
    if elapsed >= minimum:
        return
    jitter_ms = secrets.randbelow(41) + 10  # 10-50ms
    time.sleep(minimum - elapsed + (jitter_ms / 1000))


def _extract_password(payload: object) -> str:
    if isinstance(payload, Mapping):
        return str(payload.get("password") or "")
    return ""


class SecureTokenObtainPairView(TokenObtainPairView):
    """Token view that avoids account enumeration."""

    throttle_scope = "token_obtain"
    throttle_classes = [ScopedRateThrottle]
    serializer_class = SessionAwareTokenObtainPairSerializer

    def post(self, request: Request, *args: object, **kwargs: object) -> Response:
        start = time.monotonic()
        username = _extract_identifier(request.data)
        user_id, agency_id = _resolve_user_identity(username)
        source_ip = _client_ip(request)
        locked_until = auth_lockout.locked_until(identifier=username, source_ip=source_ip)
        if locked_until is not None:
            _log_auth_event(
                event_type="login_blocked",
                outcome="failure",
                request=request,
                user_id=user_id,
                agency_id=agency_id,
                identifier=username,
                reason_code="temporarily_locked",
            )
            _sleep_to_min(start, _MIN_AUTH_SECONDS)
            raise AuthenticationFailed("Too many failed attempts. Try again later.")
        _log_auth_event(
            event_type="login_attempt",
            outcome="attempt",
            request=request,
            user_id=user_id,
            agency_id=agency_id,
            identifier=username,
            reason_code="submitted",
        )
        try:
            response = super().post(request, *args, **kwargs)
        except AuthenticationFailed as exc:
            auth_lockout.record_failure(
                identifier=username,
                source_ip=source_ip,
                agency_id=agency_id,
                user_id=user_id,
                user_agent=str(request.META.get("HTTP_USER_AGENT", "") or "")[:512] or None,
                request_id=get_correlation_id(),
            )
            check_password(_extract_password(request.data), _DUMMY_HASH)
            _log_auth_event(
                event_type="login_failed",
                outcome="failure",
                request=request,
                user_id=user_id,
                agency_id=agency_id,
                identifier=username,
                reason_code="invalid_credentials",
            )
            _sleep_to_min(start, _MIN_AUTH_SECONDS)
            raise AuthenticationFailed("Invalid credentials") from exc
        # Normalize timing even for successful logins.
        check_password("constant-time", _DUMMY_HASH)
        success_user_id, success_agency_id = _resolve_user_identity(username)
        _log_auth_event(
            event_type="login_success",
            outcome="success",
            request=request,
            user_id=success_user_id,
            agency_id=success_agency_id,
            identifier=username,
            reason_code="token_issued",
        )
        auth_lockout.clear_failures(identifier=username, source_ip=source_ip)
        _sleep_to_min(start, _MIN_AUTH_SECONDS)
        return response


class SecureTokenRefreshView(TokenRefreshView):
    """Token refresh with dedicated throttling."""

    throttle_scope = "token_refresh"
    throttle_classes = [ScopedRateThrottle]
    serializer_class = SessionAwareTokenRefreshSerializer

    def post(self, request: Request, *args: object, **kwargs: object) -> Response:
        user_id, agency_id = _resolve_refresh_identity(request.data)
        _log_auth_event(
            event_type="token_refresh_attempt",
            outcome="attempt",
            request=request,
            user_id=user_id,
            agency_id=agency_id,
            identifier=str(user_id) if user_id is not None else None,
            reason_code="submitted",
        )
        try:
            response = super().post(request, *args, **kwargs)
        except AuthenticationFailed as exc:
            auth_security_alerts.record_refresh_failure(
                agency_id=agency_id,
                user_id=user_id,
                source_ip=_client_ip(request),
                user_agent=str(request.META.get("HTTP_USER_AGENT", "") or "")[:512] or None,
                request_id=get_correlation_id(),
            )
            _log_auth_event(
                event_type="token_refresh_failed",
                outcome="failure",
                request=request,
                user_id=user_id,
                agency_id=agency_id,
                identifier=str(user_id) if user_id is not None else None,
                reason_code="invalid_refresh_token",
            )
            raise AuthenticationFailed("Invalid refresh token") from exc
        _log_auth_event(
            event_type="token_refresh_success",
            outcome="success",
            request=request,
            user_id=user_id,
            agency_id=agency_id,
            identifier=str(user_id) if user_id is not None else None,
            reason_code="token_rotated",
        )
        return response


def _extract_identifier(payload: object) -> str:
    if isinstance(payload, Mapping):
        username = str(payload.get("username") or "")
        if username:
            return username
        email = str(payload.get("email") or "")
        if email:
            return email
    return ""


def _resolve_user_identity(identifier: str) -> tuple[int | None, int | None]:
    if not identifier:
        return None, None
    try:
        from django.contrib.auth import get_user_model
    except Exception:
        return None, None

    User = get_user_model()
    user = User.objects.filter(username=identifier).first()
    if not user and "@" in identifier:
        user = User.objects.filter(email=identifier).first()
    if not user:
        return None, None
    user_id = getattr(user, "id", None)
    return (int(user_id), getattr(user, "agency_id", None)) if user_id is not None else (None, None)


def _resolve_refresh_identity(payload: object) -> tuple[int | None, int | None]:
    if not isinstance(payload, Mapping):
        return None, None
    raw = payload.get("refresh")
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    try:
        token = RefreshToken(cast(Any, raw))
        user_claim = token.get("user_id")
        if user_claim is None:
            return None, None
        user_id = int(user_claim)
    except (TokenError, InvalidToken, ValueError):
        return None, None

    try:
        from django.contrib.auth import get_user_model
    except Exception:
        return user_id, None

    User = get_user_model()
    user = User.objects.filter(id=user_id).first()
    if not user:
        return user_id, None
    return user_id, getattr(user, "agency_id", None)


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
        details={"path": request.path, "method": request.method},
        fail_silently=True,
    )
