"""
User management API views.
"""

from __future__ import annotations

import math
from typing import cast

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.query_budget import guard_estimated_scan_rows
from server.api.route_registry import route
from server.api.throttling import HeaderScopedRateThrottle
from server.services import auth_events, users
from server.services.cache_control import CacheNamespace
from server.services.cache_layers import get_response_cache
from server.services.cache_policies import USERS_LIST_POLICY
from server.services.cursor_pagination import normalize_limit
from server.services.errors import NotFoundError, PermissionDeniedError
from server.services.users_types import UserCreateInput, UserUpdateInput

from .idempotency import check_idempotency, store_idempotency
from .rbac import require_manager, require_owner, require_superuser
from .request_schemas import UserCreateSerializer, UserUpdateSerializer
from .response_schemas import UserResponseSerializer
from .step_up import require_step_up
from .validation import validate_payload
from .view_helpers import (
    actor,
    error,
    list_response,
    parse_bool,
    parse_int,
    request_correlation_id,
    safe_error_message,
    safe_forbidden_message,
    safe_not_found_message,
)

_USERS_SCOPE_ALL_THROTTLE_SCOPE = "users_scope_all"


class _UsersScopeAllThrottleView:
    throttle_scope = _USERS_SCOPE_ALL_THROTTLE_SCOPE


_USERS_SCOPE_ALL_THROTTLE_VIEW = _UsersScopeAllThrottleView()


def _user_id(request: Request) -> int | None:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return int(getattr(user, "id", 0))
    return None


def _user_role(request: Request) -> str | None:
    user = getattr(request, "user", None)
    role = getattr(user, "role", None) if user else None
    return str(role) if isinstance(role, str) and role else None


def _is_owner(request: Request) -> bool:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return bool(getattr(user, "is_owner", False))
    return False


def _scope_all_throttle_response(request: Request) -> Response | None:
    throttle = HeaderScopedRateThrottle()
    throttle.scope = _USERS_SCOPE_ALL_THROTTLE_SCOPE
    if throttle.allow_request(request, cast(object, _USERS_SCOPE_ALL_THROTTLE_VIEW)):
        return None
    wait_seconds = throttle.wait()
    payload: dict[str, object] = {"detail": "Request was throttled."}
    if wait_seconds is not None:
        payload["available_in"] = max(1, int(math.ceil(wait_seconds)))
    return Response(payload, status=status.HTTP_429_TOO_MANY_REQUESTS)


def _audit_scope_all_access(
    request: Request,
    *,
    outcome: str,
    reason_code: str | None = None,
    total: int | None = None,
    role: str | None = None,
    include_inactive: bool | None = None,
    agency_id: int | None = None,
) -> None:
    details: dict[str, object] = {"scope": "all"}
    if role:
        details["role"] = role
    if include_inactive is not None:
        details["include_inactive"] = include_inactive
    if agency_id is not None:
        details["agency_id"] = agency_id
    if total is not None:
        details["total"] = total
    auth_events.log_auth_event(
        event_type="users_scope_all_list",
        outcome=outcome,
        agency_id=getattr(request.user, "agency_id", None),
        user_id=getattr(request.user, "id", None),
        identifier=actor(request),
        reason_code=reason_code,
        source_ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT"),
        request_id=request_correlation_id(request),
        details=details,
        fail_silently=True,
    )


@route("users/", order=84)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def users_list(request: Request) -> Response:
    """List or create users for an agency."""
    deny = require_manager(request)
    if deny:
        return deny

    if request.method == "POST":
        step_up_response = require_step_up(request)
        if step_up_response is not None:
            return step_up_response
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response is not None:
            return idem_response
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            UserCreateSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        try:
            created = users.create_user(
                actor=request.user,
                data=cast(UserCreateInput, payload or {}),
            )
        except PermissionDeniedError as exc:
            return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
        except NotFoundError as exc:
            return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
        data = UserResponseSerializer(created).data
        response = Response(data, status=status.HTTP_201_CREATED)
        return store_idempotency(idem_ctx, response, request)

    scope = (request.query_params.get("scope") or "agency").strip().lower()
    if scope not in {"agency", "all"}:
        return error("scope must be 'agency' or 'all'", status.HTTP_400_BAD_REQUEST)

    include_inactive = parse_bool(request.query_params.get("include_inactive"), False)
    role = request.query_params.get("role")
    q = str(request.query_params.get("q") or "").strip()
    limit_raw = request.query_params.get("limit")
    limit_value = normalize_limit(limit_raw, default=50, minimum=1, maximum=200)
    cursor = str(request.query_params.get("cursor") or "").strip() or None
    budget_response = guard_estimated_scan_rows(request, estimated_scan_rows=limit_value + 1)
    if budget_response is not None:
        return budget_response
    agency_id_raw = request.query_params.get("agency_id")
    agency_id_value = parse_int(agency_id_raw)
    if agency_id_raw is not None and agency_id_raw.strip():
        if agency_id_value is None:
            return error("agency_id must be an integer", status.HTTP_400_BAD_REQUEST)
        if agency_id_value <= 0:
            return error("agency_id must be > 0", status.HTTP_400_BAD_REQUEST)

    if scope == "all":
        superuser_deny = require_superuser(request)
        if superuser_deny:
            _audit_scope_all_access(request, outcome="denied", reason_code="not_superuser")
            return superuser_deny
        throttle_response = _scope_all_throttle_response(request)
        if throttle_response is not None:
            _audit_scope_all_access(request, outcome="throttled", reason_code="rate_limited")
            return throttle_response

    request_agency_id = getattr(request.user, "agency_id", None)
    cached_agency_id = (
        agency_id_value
        if scope == "agency" and bool(getattr(request.user, "is_superuser", False))
        else (int(request_agency_id) if isinstance(request_agency_id, int) else None)
    )

    cache_key = (
        _user_id(request),
        _user_role(request),
        _is_owner(request),
        bool(getattr(request.user, "is_superuser", False)),
        scope,
        include_inactive,
        role if role else None,
        agency_id_value,
        q if q else "",
        limit_value,
        cursor,
        (
            users.get_users_surface_generation(agency_id=int(cached_agency_id))
            if scope == "agency" and isinstance(cached_agency_id, int) and cached_agency_id > 0
            else 1
        ),
    )

    def fill_users_payload() -> dict[str, object]:
        return _build_users_list_payload(
            request=request,
            include_inactive=include_inactive,
            role=role if role else None,
            agency_id_value=agency_id_value,
            scope=scope,
            q=q if q else None,
            limit_value=limit_value,
            cursor=cursor,
        )

    try:
        if scope == "all":
            payload = fill_users_payload()
        else:
            payload = cast(
                dict[str, object],
                get_response_cache().get_or_fill(
                    namespace=CacheNamespace.USERS_LIST,
                    agency_id=cached_agency_id,
                    actor_id=getattr(request.user, "id", None),
                    query_key=cache_key,
                    policy=USERS_LIST_POLICY,
                    fill_fn=fill_users_payload,
                ),
            )
    except PermissionDeniedError as exc:
        if scope == "all":
            _audit_scope_all_access(
                request,
                outcome="denied",
                reason_code="permission_denied",
                role=role if role else None,
                include_inactive=include_inactive,
                agency_id=agency_id_value,
            )
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    if scope == "all":
        total_returned = payload.get("total_returned")
        _audit_scope_all_access(
            request,
            outcome="success",
            role=role if role else None,
            include_inactive=include_inactive,
            agency_id=agency_id_value,
            total=total_returned if isinstance(total_returned, int) else 0,
        )
    total = payload.get("total")
    response = list_response(
        payload.get("items", []),
        total=total if isinstance(total, int) else None,
    )
    response.data["next_cursor"] = payload.get("next_cursor")
    response.data["has_more"] = payload.get("has_more")
    response.data["total_returned"] = payload.get("total_returned")
    return response


@route("users/<int:user_id>/", order=85)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def user_detail(request: Request, user_id: int) -> Response:
    """Retrieve, update, or deactivate a user."""
    deny = require_manager(request)
    if deny:
        return deny

    if request.method == "GET":
        try:
            user = users.get_user_detail(actor=request.user, user_id=user_id)
        except PermissionDeniedError as exc:
            return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
        except NotFoundError as exc:
            return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
        data = UserResponseSerializer(user).data
        return Response(data)

    if request.method == "PUT":
        step_up_response = require_step_up(request)
        if step_up_response is not None:
            return step_up_response
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response is not None:
            return idem_response
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            UserUpdateSerializer,
            partial=True,
        )
        if error_response:
            return error_response
        try:
            updated = users.update_user(
                actor=request.user,
                user_id=user_id,
                data=cast(UserUpdateInput, payload or {}),
            )
        except PermissionDeniedError as exc:
            return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
        except NotFoundError as exc:
            return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
        data = UserResponseSerializer(updated).data
        response = Response(data)
        return store_idempotency(idem_ctx, response, request)

    # DELETE (deactivate)
    step_up_response = require_step_up(request)
    if step_up_response is not None:
        return step_up_response
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    deny = require_owner(request)
    if deny:
        return deny
    try:
        users.deactivate_user(actor=request.user, user_id=user_id)
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


__all__ = ["user_detail", "users_list"]


def _build_users_list_payload(
    *,
    request: Request,
    include_inactive: bool,
    role: str | None,
    agency_id_value: int | None,
    scope: str,
    q: str | None,
    limit_value: int,
    cursor: str | None,
) -> dict[str, object]:
    items, next_cursor, has_more = users.list_users_page(
        actor=request.user,
        include_inactive=include_inactive,
        role=role,
        agency_id=agency_id_value,
        scope=scope,
        q=q,
        limit=limit_value,
        cursor=cursor,
    )
    data = UserResponseSerializer(items, many=True).data
    return {
        "items": data,
        "next_cursor": next_cursor,
        "has_more": bool(has_more),
        "total_returned": len(data),
        "total": len(data),
    }
