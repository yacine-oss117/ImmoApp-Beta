"""JWT serializers/authentication with MFA + session tracking."""

from __future__ import annotations

import os
from typing import Any, cast

from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken, Token

from core.env_flags import auth_session_tracking_enabled
from server.services import auth_events, auth_sessions, mfa_totp
from server.services.accounts_ale import resolve_user_mfa_secret


def _session_tracking_enabled() -> bool:
    return auth_session_tracking_enabled()


def _request_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", "") or "")
    source_ip: str | None = None
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            source_ip = parts[0]
    if source_ip is None:
        remote = str(request.META.get("REMOTE_ADDR", "") or "").strip()
        source_ip = remote or None
    user_agent = str(request.META.get("HTTP_USER_AGENT", "") or "").strip()[:512] or None
    return source_ip, user_agent


def _mfa_enforced_roles() -> set[str]:
    raw = os.environ.get("IMMOAPP_MFA_ENFORCE_ROLES", "manager,owner")
    return {token.strip().lower() for token in raw.split(",") if token.strip()}


def _mfa_required_for_user(user: object) -> bool:
    if bool(getattr(user, "is_superuser", False)):
        return False
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role in _mfa_enforced_roles():
        return True
    if "owner" in _mfa_enforced_roles() and bool(getattr(user, "is_owner", False)):
        return True
    return bool(getattr(user, "mfa_totp_enabled", False))


def _validated_refresh_token(raw: str) -> Token:
    return RefreshToken(cast(Any, raw))


def _refresh_subject(raw: str) -> tuple[Token, object]:
    try:
        token = _validated_refresh_token(raw)
    except TokenError as exc:
        raise AuthenticationFailed("Invalid refresh token.") from exc
    user_id = token.get("user_id")
    try:
        resolved_user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise AuthenticationFailed("Invalid refresh token.") from exc
    User = get_user_model()
    user = User.objects.filter(id=resolved_user_id).first()
    if user is None or not getattr(user, "is_active", False):
        raise AuthenticationFailed("Invalid refresh token.")
    return token, user


def _apply_identity_claims(token: Token, user: object) -> Token:
    agency_id = getattr(user, "agency_id", None)
    if agency_id is not None:
        token["agency_id"] = int(agency_id)
    resolved_user_id = getattr(user, "id", None)
    if resolved_user_id is not None:
        token["user_id"] = int(resolved_user_id)
        token["sub"] = str(int(resolved_user_id))
    role = str(getattr(user, "role", "") or "").strip()
    if role:
        token["role"] = role
    token["is_owner"] = bool(getattr(user, "is_owner", False))
    return token


class SessionAwareTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Token pair serializer with optional TOTP MFA requirement."""

    mfa_code = serializers.CharField(required=False, allow_blank=True, max_length=16)

    @classmethod
    def get_token(cls, user: object) -> Token:
        token = super().get_token(cast(Any, user))
        return _apply_identity_claims(token, user)

    def validate(self, attrs: dict[str, object]) -> dict[str, str]:
        if not _session_tracking_enabled():
            payload = {
                self.username_field: str(attrs.get(self.username_field) or ""),
                "password": str(attrs.get("password") or ""),
            }
            return super().validate(payload)
        username_value = str(attrs.get(self.username_field) or "")
        password = str(attrs.get("password") or "")
        mfa_code = str(attrs.get("mfa_code") or "")
        request = self.context.get("request")
        request_obj = request if isinstance(request, Request) else None
        source_ip, user_agent = _request_meta(request_obj)

        self.user = authenticate(request=request_obj, username=username_value, password=password)
        if self.user is None or not getattr(self.user, "is_active", False):
            raise AuthenticationFailed("Invalid credentials")

        if _mfa_required_for_user(self.user):
            secret = resolve_user_mfa_secret(self.user)
            if not secret:
                auth_events.log_auth_event(
                    event_type="mfa_totp_verify",
                    outcome="failure",
                    agency_id=getattr(self.user, "agency_id", None),
                    user_id=getattr(self.user, "id", None),
                    identifier=str(getattr(self.user, "username", "") or ""),
                    reason_code="totp_not_enrolled",
                    source_ip=source_ip,
                    user_agent=user_agent,
                    fail_silently=True,
                )
                raise AuthenticationFailed("MFA enrollment required.")
            if not mfa_totp.verify_code(secret=secret, code=mfa_code):
                auth_events.log_auth_event(
                    event_type="mfa_totp_verify",
                    outcome="failure",
                    agency_id=getattr(self.user, "agency_id", None),
                    user_id=getattr(self.user, "id", None),
                    identifier=str(getattr(self.user, "username", "") or ""),
                    reason_code="invalid_totp",
                    source_ip=source_ip,
                    user_agent=user_agent,
                    fail_silently=True,
                )
                raise AuthenticationFailed("MFA code required or invalid.")
            auth_events.log_auth_event(
                event_type="mfa_totp_verify",
                outcome="success",
                agency_id=getattr(self.user, "agency_id", None),
                user_id=getattr(self.user, "id", None),
                identifier=str(getattr(self.user, "username", "") or ""),
                reason_code="totp_valid",
                source_ip=source_ip,
                user_agent=user_agent,
                fail_silently=True,
            )

        session = auth_sessions.issue_session(
            user=self.user,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        refresh = cast(RefreshToken, self.get_token(self.user))
        refresh["sid"] = str(session.session_id)
        auth_sessions.bind_refresh_jti(
            session_id=session.session_id, refresh_jti=str(refresh.get("jti", ""))
        )

        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


class SessionAwareTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh serializer that keeps session state synchronized."""

    def validate(self, attrs: dict[str, object]) -> dict[str, str]:
        raw = str(attrs.get("refresh") or "")
        token, user = _refresh_subject(raw)
        sid = token.get("sid")
        token_iat = token.get("iat")
        current_refresh_jti = str(token.get("jti") or "")

        request = self.context.get("request")
        request_obj = request if isinstance(request, Request) else None
        source_ip, user_agent = _request_meta(request_obj)

        if _session_tracking_enabled():
            ok, _reason = auth_sessions.validate_token_session(
                user=user,
                session_id=sid,
                token_iat=token_iat,
            )
            if not ok:
                auth_events.log_auth_event(
                    event_type="token_refresh_failed",
                    outcome="failure",
                    agency_id=getattr(user, "agency_id", None),
                    user_id=getattr(user, "id", None),
                    identifier=str(getattr(user, "username", "") or ""),
                    reason_code="session_revoked",
                    source_ip=source_ip,
                    user_agent=user_agent,
                    fail_silently=True,
                )
                raise AuthenticationFailed("Session revoked or expired.")

        try:
            payload = super().validate(attrs)
        except (AuthenticationFailed, TokenError) as exc:
            raise AuthenticationFailed("Invalid refresh token.") from exc

        if _session_tracking_enabled() and "refresh" in payload:
            try:
                rotated = _validated_refresh_token(str(payload.get("refresh") or ""))
                rotated_refresh_jti = str(rotated.get("jti", ""))
                auth_sessions.bind_refresh_jti(
                    session_id=sid,
                    refresh_jti=rotated_refresh_jti or current_refresh_jti,
                )
            except TokenError as exc:
                raise AuthenticationFailed("Invalid refresh token.") from exc
        elif _session_tracking_enabled():
            auth_sessions.touch_session(session_id=sid)
        return payload


class SessionAwareJWTAuthentication(JWTAuthentication):
    """JWT auth that rejects revoked/expired tracked sessions."""

    def get_user(self, validated_token: Token) -> object:  # type: ignore[override]
        user = super().get_user(validated_token)
        if not getattr(user, "is_active", False):
            raise AuthenticationFailed("User is inactive.")
        return user

    def authenticate(self, request: Request) -> tuple[object, Token] | None:  # type: ignore[override]
        result = super().authenticate(request)
        if result is None:
            return None
        if not _session_tracking_enabled():
            return result
        user, validated_token = result
        sid = validated_token.get("sid")
        iat = validated_token.get("iat")
        ok, _reason = auth_sessions.validate_token_session(user=user, session_id=sid, token_iat=iat)
        if not ok:
            raise AuthenticationFailed("Session revoked or expired.")
        return user, validated_token


__all__ = [
    "SessionAwareJWTAuthentication",
    "SessionAwareTokenObtainPairSerializer",
    "SessionAwareTokenRefreshSerializer",
]
