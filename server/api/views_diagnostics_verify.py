"""Diagnostics signature verification endpoint."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import diagnostics_keys
from server.services.errors import PermissionDeniedError

from .request_schemas_diagnostics import DiagnosticsVerifySerializer
from .validation import validate_payload
from .view_helpers import error, request_correlation_id, safe_error_message, safe_forbidden_message
from .views_diagnostics_keys import _client_ip, _user_agent


@route("diagnostics/verify/", order=139)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def diagnostics_verify(request: Request) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        DiagnosticsVerifySerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    try:
        result = diagnostics_keys.verify_diagnostics_signature(
            actor=request.user,
            device_id=str(data.get("device_id") or ""),
            signature_key_id=str(data.get("signature_key_id") or ""),
            payload=data.get("payload"),
            signature=str(data.get("signature") or ""),
            payload_version=str(data.get("payload_version") or "") or None,
            algorithm=str(data.get("algorithm") or "") or None,
            request_id=request_correlation_id(request),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_200_OK)


__all__ = ["diagnostics_verify"]
