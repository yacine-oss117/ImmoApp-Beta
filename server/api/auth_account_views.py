"""Account lifecycle auth endpoints (forgot/reset/activation)."""

from __future__ import annotations

import os

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.logging_config import get_correlation_id
from server.services import auth_events, mfa_totp, user_auth_lifecycle
from server.services.accounts_ale import resolve_user_mfa_secret
from server.services.errors import PermissionDeniedError

from .request_schemas_auth import (
    PasswordForgotSerializer,
    PasswordResetSerializer,
    StepUpAuthSerializer,
)
from .step_up import issue_step_up_token, step_up_max_age_seconds


def _client_ip(request: Request) -> str | None:
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", "") or "")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[0]
    remote = str(request.META.get("REMOTE_ADDR", "") or "").strip()
    return remote or None


def _user_agent(request: Request) -> str | None:
    value = str(request.META.get("HTTP_USER_AGENT", "") or "").strip()
    return value[:512] or None


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


class PasswordForgotView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_forgot"

    def post(self, request: Request) -> Response:
        serializer = PasswordForgotSerializer(
            data=request.data if isinstance(request.data, dict) else {}
        )
        serializer.is_valid(raise_exception=True)
        payload = user_auth_lifecycle.request_password_reset(
            identifier=str(serializer.validated_data["identifier"]),
            request_id=get_correlation_id(),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
        return Response(payload, status=status.HTTP_200_OK)


class PasswordResetView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request: Request) -> Response:
        serializer = PasswordResetSerializer(
            data=request.data if isinstance(request.data, dict) else {}
        )
        serializer.is_valid(raise_exception=True)
        try:
            payload = user_auth_lifecycle.reset_password_with_token(
                token=str(serializer.validated_data["token"]),
                new_password=str(serializer.validated_data["new_password"]),
                request_id=get_correlation_id(),
                source_ip=_client_ip(request),
                user_agent=_user_agent(request),
            )
        except PermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload, status=status.HTTP_200_OK)


class AccountActivateView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "account_activate"

    def post(self, request: Request) -> Response:
        return Response(
            {
                "code": "LEGACY_ACTIVATION_RETIRED",
                "detail": "Legacy activation endpoint is retired. Use /api/v1/auth/activate/.",
            },
            status=status.HTTP_410_GONE,
        )


class StepUpAuthView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "step_up_auth"

    def post(self, request: Request) -> Response:
        serializer = StepUpAuthSerializer(
            data=request.data if isinstance(request.data, dict) else {}
        )
        serializer.is_valid(raise_exception=True)
        password = str(serializer.validated_data["password"])
        mfa_code = str(serializer.validated_data.get("mfa_code") or "")
        user = request.user
        check_password = getattr(user, "check_password", None)
        password_ok = bool(callable(check_password) and check_password(password))
        if not password_ok:
            auth_events.log_auth_event(
                event_type="step_up_auth",
                outcome="failure",
                agency_id=getattr(user, "agency_id", None),
                user_id=getattr(user, "id", None),
                identifier=str(getattr(user, "username", "") or ""),
                reason_code="invalid_password",
                source_ip=_client_ip(request),
                user_agent=_user_agent(request),
                request_id=get_correlation_id(),
                fail_silently=True,
            )
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_403_FORBIDDEN)
        if _mfa_required_for_user(user):
            secret = resolve_user_mfa_secret(user)
            if not secret:
                auth_events.log_auth_event(
                    event_type="step_up_auth",
                    outcome="failure",
                    agency_id=getattr(user, "agency_id", None),
                    user_id=getattr(user, "id", None),
                    identifier=str(getattr(user, "username", "") or ""),
                    reason_code="mfa_not_enrolled",
                    source_ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    request_id=get_correlation_id(),
                    fail_silently=True,
                )
                return Response(
                    {"detail": "MFA enrollment required."}, status=status.HTTP_403_FORBIDDEN
                )
            if not mfa_totp.verify_code(secret=secret, code=mfa_code):
                auth_events.log_auth_event(
                    event_type="step_up_auth",
                    outcome="failure",
                    agency_id=getattr(user, "agency_id", None),
                    user_id=getattr(user, "id", None),
                    identifier=str(getattr(user, "username", "") or ""),
                    reason_code="invalid_mfa_code",
                    source_ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    request_id=get_correlation_id(),
                    fail_silently=True,
                )
                return Response(
                    {"detail": "MFA code required or invalid."}, status=status.HTTP_403_FORBIDDEN
                )

        token = issue_step_up_token(user_id=int(user.id))
        auth_events.log_auth_event(
            event_type="step_up_auth",
            outcome="success",
            agency_id=getattr(user, "agency_id", None),
            user_id=getattr(user, "id", None),
            identifier=str(getattr(user, "username", "") or ""),
            reason_code="issued",
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
            request_id=get_correlation_id(),
            fail_silently=True,
        )
        return Response(
            {
                "step_up_token": token,
                "expires_in_seconds": step_up_max_age_seconds(),
                "header": "X-Immoapp-Step-Up",
            },
            status=status.HTTP_200_OK,
        )


__all__ = ["AccountActivateView", "PasswordForgotView", "PasswordResetView", "StepUpAuthView"]
