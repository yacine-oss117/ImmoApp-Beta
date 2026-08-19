"""Session/device management endpoints."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import auth_sessions
from server.services.errors import NotFoundError, PermissionDeniedError

from .request_schemas_auth import SessionRevokeAllSerializer
from .step_up import require_step_up
from .validation import validate_payload
from .view_helpers import error, safe_forbidden_message, safe_not_found_message


def _current_sid(request: Request) -> str | None:
    token = getattr(request, "auth", None)
    if token is None:
        return None
    sid = token.get("sid") if hasattr(token, "get") else None
    return str(sid).strip() if sid else None


@route("auth/sessions/", order=150)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_sessions_list(request: Request) -> Response:
    items = auth_sessions.list_user_sessions(user=request.user)
    current_sid = _current_sid(request)
    for item in items:
        item["is_current"] = bool(current_sid and item.get("session_id") == current_sid)
    return Response({"items": items, "total": len(items)}, status=status.HTTP_200_OK)


@route("auth/sessions/<uuid:session_id>/revoke/", order=151)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def auth_sessions_revoke(request: Request, session_id: Any) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    try:
        auth_sessions.revoke_session(
            actor=request.user, session_id=session_id, reason="single_revoke"
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("auth/sessions/revoke-all/", order=152)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def auth_sessions_revoke_all(request: Request) -> Response:
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        SessionRevokeAllSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    keep_current = bool((payload or {}).get("keep_current", True))
    count = auth_sessions.revoke_all_sessions(
        actor=request.user,
        except_session_id=_current_sid(request) if keep_current else None,
    )
    return Response({"revoked": count}, status=status.HTTP_200_OK)


__all__ = ["auth_sessions_list", "auth_sessions_revoke", "auth_sessions_revoke_all"]
