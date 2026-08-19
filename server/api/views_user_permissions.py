"""Privilege elevation request/approval API endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.rbac import require_manager, require_owner
from server.api.route_registry import route
from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.services import permission_elevation
from server.services.errors import NotFoundError, PermissionDeniedError

from .request_schemas_permission_elevation import (
    PrivilegeDecisionSerializer,
    PrivilegeListQuerySerializer,
    PrivilegeRequestCreateSerializer,
)
from .step_up import require_step_up
from .validation import validate_payload
from .view_helpers import error, safe_error_message, safe_forbidden_message, safe_not_found_message


class PrivilegeActor(Protocol):
    id: int
    username: str
    role: str
    agency_id: int | None
    is_owner: bool
    is_superuser: bool


def _bool_owner(request: Request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and getattr(user, "is_owner", False))


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _privilege_throttle(view: Callable[..., object]) -> Callable[..., object]:
    view.throttle_scope = "privilege_elevation"  # type: ignore[attr-defined]
    return view


def _effective_matrix(request: Request) -> list[dict[str, object]]:
    user = getattr(request, "user", None)
    actor_id = int(getattr(user, "id", 0) or 0)
    actor_agency_id = getattr(user, "agency_id", None)
    User = get_user_model()
    qs = User.objects.order_by("role", "username")
    if not getattr(user, "is_superuser", False):
        qs = qs.filter(agency_id=actor_agency_id)
        if not _bool_owner(request):
            qs = qs.filter(Q(id=actor_id) | Q(manager_id=actor_id))
    rows: list[dict[str, object]] = []
    for row in qs[:1000]:
        typed_row = cast(PrivilegeActor, row)
        rows.append(
            {
                "user_id": int(typed_row.id),
                "username": str(typed_row.username or ""),
                "role": str(typed_row.role or ""),
                "agency_id": int(typed_row.agency_id) if typed_row.agency_id is not None else None,
                "is_owner": bool(typed_row.is_owner),
                "permissions": permission_elevation.list_effective_permissions(user=typed_row),
            }
        )
    return rows


@route("users/permissions/grants/", order=153)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_privilege_throttle
def user_permission_grants(request: Request) -> Response:
    deny = require_manager(request)
    if deny:
        return deny
    if request.method == "GET":
        serializer = PrivilegeListQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return error("Invalid query params.", status.HTTP_400_BAD_REQUEST)
        try:
            items = permission_elevation.list_requests(
                actor=request.user,
                user_id=serializer.validated_data.get("user_id"),
                status=serializer.validated_data.get("status"),
            )
        except PermissionDeniedError as exc:
            return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
        return Response({"items": items, "total": len(items)}, status=status.HTTP_200_OK)

    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        PrivilegeRequestCreateSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    user_id = _optional_int(payload.get("user_id"))
    if user_id is None:
        return error("user_id is required", status.HTTP_400_BAD_REQUEST)
    try:
        created = permission_elevation.request_elevation(
            actor=request.user,
            user_id=user_id,
            permission=str(payload.get("permission") or ""),
            reason=str(payload.get("reason") or ""),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(created, status=status.HTTP_201_CREATED)


@route("users/permissions/grants/<int:request_id>/approve/", order=154)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_privilege_throttle
def user_permission_grant_approve(request: Request, request_id: int) -> Response:
    deny = require_owner(request)
    if deny:
        return deny
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        PrivilegeDecisionSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    try:
        item = permission_elevation.decide_request(
            actor=request.user,
            request_id=request_id,
            approve=True,
            reason=str(payload.get("reason") or ""),
            duration_minutes=_optional_int(payload.get("duration_minutes")),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(item, status=status.HTTP_200_OK)


@route("users/permissions/grants/<int:request_id>/deny/", order=155)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_privilege_throttle
def user_permission_grant_deny(request: Request, request_id: int) -> Response:
    deny = require_owner(request)
    if deny:
        return deny
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        PrivilegeDecisionSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    try:
        item = permission_elevation.decide_request(
            actor=request.user,
            request_id=request_id,
            approve=False,
            reason=str(payload.get("reason") or ""),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(item, status=status.HTTP_200_OK)


@route("users/permissions/grants/<int:request_id>/revoke/", order=156)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_privilege_throttle
def user_permission_grant_revoke(request: Request, request_id: int) -> Response:
    deny = require_owner(request)
    if deny:
        return deny
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        PrivilegeDecisionSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    try:
        item = permission_elevation.revoke_request(
            actor=request.user,
            request_id=request_id,
            reason=str(payload.get("reason") or ""),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(item, status=status.HTTP_200_OK)


@route("users/permissions/matrix/", order=157)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_privilege_throttle
def user_permissions_matrix(request: Request) -> Response:
    deny = require_manager(request)
    if deny:
        return deny
    rows = _effective_matrix(request)
    return Response({"items": rows, "total": len(rows)}, status=status.HTTP_200_OK)


__all__ = [
    "user_permission_grant_approve",
    "user_permission_grant_deny",
    "user_permission_grant_revoke",
    "user_permission_grants",
    "user_permissions_matrix",
]
