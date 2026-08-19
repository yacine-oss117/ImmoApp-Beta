"""Notification API endpoints."""

from __future__ import annotations

from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.query_budget import guard_estimated_scan_rows
from server.api.route_registry import route
from server.services import notifications
from server.services.cache_control import CacheNamespace
from server.services.cache_layers import get_response_cache
from server.services.cache_policies import NOTIFICATIONS_COUNT_POLICY, NOTIFICATIONS_LIST_POLICY

from .rbac import require_superuser
from .request_schemas import NotificationsMarkSerializer
from .validation import validate_payload
from .view_helpers import is_superuser, list_response, parse_int


def _user_role(request: Request) -> str | None:
    user = getattr(request, "user", None)
    role = getattr(user, "role", None) if user else None
    return str(role) if isinstance(role, str) and role else None


def _user_id(request: Request) -> int | None:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return int(getattr(user, "id", 0))
    return None


def _is_owner(request: Request) -> bool:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return bool(getattr(user, "is_owner", False))
    return False


def _parse_ids(raw: object) -> list[int]:
    if not isinstance(raw, (list, tuple)):
        return []
    ids: list[int] = []
    for item in raw:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _parse_bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y"}
    if isinstance(raw, int):
        return raw != 0
    return False


@route("notifications/", order=115)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_list(request: Request) -> Response:
    limit = parse_int(request.query_params.get("limit"), 200) or 200
    offset = parse_int(request.query_params.get("offset"), 0) or 0
    cursor = parse_int(request.query_params.get("cursor"))
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    if cursor is not None:
        offset = 0
    budget_response = guard_estimated_scan_rows(
        request,
        estimated_scan_rows=limit if cursor is not None else (limit + offset),
    )
    if budget_response is not None:
        return budget_response

    user_id = _user_id(request)
    role = _user_role(request)
    owner_flag = _is_owner(request)
    superuser_flag = is_superuser(request)
    cache_key = (
        user_id,
        role,
        owner_flag,
        superuser_flag,
        limit,
        offset,
        cursor,
        notifications.get_notifications_scope_generations(
            user_id=user_id,
            role=role,
            is_owner=owner_flag,
            is_superuser=superuser_flag,
            agency_id=getattr(request.user, "agency_id", None),
        ),
    )
    use_cache = cursor is not None or (offset + limit <= 500)
    if use_cache:
        payload = get_response_cache().get_or_fill(
            namespace=CacheNamespace.NOTIFICATIONS_LIST,
            agency_id=getattr(request.user, "agency_id", None),
            actor_id=user_id,
            query_key=cache_key,
            policy=NOTIFICATIONS_LIST_POLICY,
            fill_fn=lambda: _build_notifications_list_payload(
                user_id=user_id,
                role=role,
                owner_flag=owner_flag,
                superuser_flag=superuser_flag,
                limit=limit,
                offset=offset,
                cursor=cursor,
            ),
        )
    else:
        payload = _build_notifications_list_payload(
            user_id=user_id,
            role=role,
            owner_flag=owner_flag,
            superuser_flag=superuser_flag,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
    if not isinstance(payload, dict):
        payload = {}
    total = payload.get("total")
    response = list_response(
        payload.get("items", []),
        total=total if isinstance(total, int) else None,
    )
    response.data["next_cursor"] = payload.get("next_cursor")
    return response


@route("notifications/clear/", order=116)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_clear(request: Request) -> Response:
    deleted = notifications.clear_visible_notifications(
        agency_id=getattr(request.user, "agency_id", None),
        user_id=_user_id(request),
        role=_user_role(request),
        is_owner=_is_owner(request),
        is_superuser=is_superuser(request),
    )
    return Response({"deleted": deleted})


@route("notifications/mark-read/", order=117)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_mark_read(request: Request) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        NotificationsMarkSerializer,
        partial=True,
    )
    if error_response:
        return error_response
    payload = payload or {}
    mark_all = _parse_bool(payload.get("all"))
    ids = _parse_ids(payload.get("ids", []))
    updated = notifications.mark_notifications_read(
        agency_id=getattr(request.user, "agency_id", None),
        user_id=_user_id(request),
        role=_user_role(request),
        is_owner=_is_owner(request),
        is_superuser=is_superuser(request),
        notification_ids=ids,
        mark_all=mark_all,
    )
    return Response({"updated": updated})


@route("notifications/mark-unread/", order=118)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_mark_unread(request: Request) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        NotificationsMarkSerializer,
        partial=True,
    )
    if error_response:
        return error_response
    payload = payload or {}
    mark_all = _parse_bool(payload.get("all"))
    ids = _parse_ids(payload.get("ids", []))
    updated = notifications.mark_notifications_unread(
        agency_id=getattr(request.user, "agency_id", None),
        user_id=_user_id(request),
        role=_user_role(request),
        is_owner=_is_owner(request),
        is_superuser=is_superuser(request),
        notification_ids=ids,
        mark_all=mark_all,
    )
    return Response({"updated": updated})


@route("notifications/unread-count/", order=119)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_unread_count(request: Request) -> Response:
    payload = get_response_cache().get_or_fill(
        namespace=CacheNamespace.NOTIFICATIONS_COUNT,
        agency_id=getattr(request.user, "agency_id", None),
        actor_id=_user_id(request),
        query_key=(
            _user_id(request),
            _user_role(request),
            _is_owner(request),
            is_superuser(request),
            "unread",
            notifications.get_notifications_scope_generations(
                user_id=_user_id(request),
                role=_user_role(request),
                is_owner=_is_owner(request),
                is_superuser=is_superuser(request),
                agency_id=getattr(request.user, "agency_id", None),
            ),
        ),
        policy=NOTIFICATIONS_COUNT_POLICY,
        fill_fn=lambda: {
            "unread": notifications.count_unread_notifications(
                user_id=_user_id(request),
                role=_user_role(request),
                is_owner=_is_owner(request),
                is_superuser=is_superuser(request),
            )
        },
    )
    return Response(payload)


@route("notifications/purge/", order=120)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_purge(request: Request) -> Response:
    deny = require_superuser(request)
    if deny:
        return deny
    deleted = notifications.purge_notifications_older_than(days=60)
    return Response({"deleted": deleted})


__all__ = [
    "notifications_clear",
    "notifications_list",
    "notifications_mark_read",
    "notifications_mark_unread",
    "notifications_purge",
    "notifications_unread_count",
]


def _build_notifications_list_payload(
    *,
    user_id: int | None,
    role: str | None,
    owner_flag: bool,
    superuser_flag: bool,
    limit: int,
    offset: int,
    cursor: int | None,
) -> dict[str, object]:
    items, total = notifications.list_notification_items_with_total(
        user_id=user_id,
        role=role,
        is_owner=owner_flag,
        is_superuser=superuser_flag,
        limit=limit,
        offset=offset,
        cursor=cursor,
    )
    next_cursor: int | None = None
    if items and len(items) == limit:
        last_id = items[-1].get("id")
        if isinstance(last_id, int) and last_id > 0:
            next_cursor = last_id
    return {"items": items, "total": total, "next_cursor": next_cursor}
