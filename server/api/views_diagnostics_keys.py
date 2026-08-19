"""Diagnostics signing key enrollment and lifecycle endpoints."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import diagnostics_keys
from server.services.errors import NotFoundError, PermissionDeniedError

from .request_schemas_diagnostics import (
    DiagnosticsEnrollmentTokenSerializer,
    DiagnosticsKeyRegisterSerializer,
    DiagnosticsKeyRevokeSerializer,
    DiagnosticsKeyRotateSerializer,
)
from .step_up import require_step_up
from .validation import validate_payload
from .view_helpers import (
    error,
    request_correlation_id,
    safe_error_message,
    safe_forbidden_message,
    safe_not_found_message,
)


def _client_ip(request: Request) -> str | None:
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", "") or "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    remote = str(request.META.get("REMOTE_ADDR", "") or "").strip()
    return remote or None


def _user_agent(request: Request) -> str | None:
    value = str(request.META.get("HTTP_USER_AGENT", "") or "").strip()
    return value[:512] or None


@route("diagnostics/keys/enrollment-token/", order=135)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def diagnostics_key_enrollment_token(request: Request) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        DiagnosticsEnrollmentTokenSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    expires_seconds_raw = data.get("expires_seconds")
    expires_seconds = expires_seconds_raw if isinstance(expires_seconds_raw, int) else None
    try:
        result = diagnostics_keys.issue_enrollment_token(
            actor=request.user,
            device_id=str(data.get("device_id") or "") or None,
            expires_seconds=expires_seconds,
            request_id=request_correlation_id(request),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_201_CREATED)


@route("diagnostics/keys/register/", order=136)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def diagnostics_key_register(request: Request) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        DiagnosticsKeyRegisterSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    try:
        result = diagnostics_keys.register_signing_key(
            actor=request.user,
            device_id=str(data.get("device_id") or ""),
            signature_key_id=str(data.get("signature_key_id") or ""),
            public_key=str(data.get("public_key") or ""),
            enrollment_token=str(data.get("enrollment_token") or "") or None,
            admin_approved=bool(data.get("admin_approved", False)),
            request_id=request_correlation_id(request),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_201_CREATED)


@route("diagnostics/keys/rotate/", order=137)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def diagnostics_key_rotate(request: Request) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        DiagnosticsKeyRotateSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    try:
        result = diagnostics_keys.rotate_signing_key(
            actor=request.user,
            device_id=str(data.get("device_id") or ""),
            signature_key_id=str(data.get("signature_key_id") or ""),
            public_key=str(data.get("public_key") or ""),
            request_id=request_correlation_id(request),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_200_OK)


@route("diagnostics/keys/revoke/", order=138)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def diagnostics_key_revoke(request: Request) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        DiagnosticsKeyRevokeSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    try:
        result = diagnostics_keys.revoke_signing_key(
            actor=request.user,
            device_id=str(data.get("device_id") or ""),
            signature_key_id=str(data.get("signature_key_id") or "") or None,
            request_id=request_correlation_id(request),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_200_OK)


__all__ = [
    "diagnostics_key_enrollment_token",
    "diagnostics_key_register",
    "diagnostics_key_revoke",
    "diagnostics_key_rotate",
]
