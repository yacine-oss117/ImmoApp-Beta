"""MFA management endpoints."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import mfa_service
from server.services.errors import PermissionDeniedError

from .request_schemas_auth import TotpCodeSerializer
from .step_up import require_step_up
from .validation import validate_payload
from .view_helpers import error, safe_forbidden_message


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


@route("auth/mfa/totp/", order=146)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mfa_totp_status(request: Request) -> Response:
    return Response(mfa_service.get_status(actor=request.user))


@route("auth/mfa/totp/enroll/start/", order=147)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mfa_totp_enroll_start(request: Request) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload = mfa_service.start_totp_enrollment(
        actor=request.user,
        source_ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return Response(payload, status=status.HTTP_200_OK)


@route("auth/mfa/totp/enroll/confirm/", order=148)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mfa_totp_enroll_confirm(request: Request) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        TotpCodeSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    try:
        out = mfa_service.confirm_totp_enrollment(
            actor=request.user,
            code=str((payload or {}).get("code") or ""),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    return Response(out, status=status.HTTP_200_OK)


@route("auth/mfa/totp/disable/", order=149)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mfa_totp_disable(request: Request) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        TotpCodeSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    try:
        out = mfa_service.disable_totp(
            actor=request.user,
            code=str((payload or {}).get("code") or ""),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    return Response(out, status=status.HTTP_200_OK)


__all__ = [
    "mfa_totp_disable",
    "mfa_totp_enroll_confirm",
    "mfa_totp_enroll_start",
    "mfa_totp_status",
]
