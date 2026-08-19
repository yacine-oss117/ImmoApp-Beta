"""User invitation lifecycle API views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from rest_framework import status
from rest_framework.decorators import permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.query_budget import guard_estimated_scan_rows
from server.api.route_registry import route
from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.services import registration_lifecycle
from server.services.cache_control import CacheNamespace
from server.services.cache_layers import get_response_cache
from server.services.cache_policies import INVITES_LIST_POLICY
from server.services.cursor_pagination import normalize_limit
from server.services.errors import NotFoundError, PermissionDeniedError

from .request_schemas_user_invites import UserInviteCreateSerializer, UserInviteResendSerializer
from .validation import validate_payload
from .view_helpers import error, safe_error_message, safe_forbidden_message, safe_not_found_message


class InviteActor(Protocol):
    id: int
    agency_id: int | None
    role: str | None
    is_owner: bool
    is_superuser: bool


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


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _invite_resend_throttle(view: Callable[..., object]) -> Callable[..., object]:
    view.throttle_scope = "invite_resend"  # type: ignore[attr-defined]
    return view


@route("users/invites/", order=141)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def users_invites(request: Request) -> Response:
    if request.method == "GET":
        limit = normalize_limit(
            request.query_params.get("limit"), default=50, minimum=1, maximum=200
        )
        budget_response = guard_estimated_scan_rows(request, estimated_scan_rows=limit + 1)
        if budget_response is not None:
            return budget_response
        cursor = str(request.query_params.get("cursor") or "").strip() or None
        try:
            cache_key = (
                _user_id(request),
                _user_role(request),
                _is_owner(request),
                bool(getattr(request.user, "is_superuser", False)),
                limit,
                cursor,
                registration_lifecycle.get_pending_invites_surface_generation(actor=request.user),
            )
            payload = get_response_cache().get_or_fill(
                namespace=CacheNamespace.INVITES_LIST,
                agency_id=getattr(request.user, "agency_id", None),
                actor_id=getattr(request.user, "id", None),
                query_key=cache_key,
                policy=INVITES_LIST_POLICY,
                fill_fn=lambda: _build_invites_list_payload(
                    actor=request.user,
                    limit=limit,
                    cursor=cursor,
                ),
            )
        except PermissionDeniedError as exc:
            return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
        return Response(payload)

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        UserInviteCreateSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    try:
        created = registration_lifecycle.create_user_invite(
            actor=request.user,
            data=payload or {},
        )
    except registration_lifecycle.EmailQueueUnavailableError:
        return Response(
            {
                "code": "EMAIL_QUEUE_UNAVAILABLE",
                "detail": "Email delivery queue is temporarily unavailable.",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(created, status=status.HTTP_201_CREATED)


@route("users/invites/<uuid:invite_id>/resend/", order=142)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_invite_resend_throttle
def users_invite_resend(request: Request, invite_id: UUID) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        UserInviteResendSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    try:
        result = registration_lifecycle.resend_invite(
            actor=request.user,
            invite_id=str(invite_id),
            expires_seconds=_optional_int(payload.get("expires_seconds")),
        )
    except registration_lifecycle.EmailQueueUnavailableError:
        return Response(
            {
                "code": "EMAIL_QUEUE_UNAVAILABLE",
                "detail": "Email delivery queue is temporarily unavailable.",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except registration_lifecycle.InviteResendCooldownError as exc:
        response = Response(
            {
                "code": "INVITE_RESEND_COOLDOWN",
                "detail": "Invite resend is on cooldown.",
                "retry_after_seconds": exc.retry_after_seconds,
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = str(exc.retry_after_seconds)
        return response
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_200_OK)


@route("users/invites/<uuid:invite_id>/revoke/", order=143)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def users_invite_revoke(request: Request, invite_id: UUID) -> Response:
    try:
        result = registration_lifecycle.revoke_invite(actor=request.user, invite_id=str(invite_id))
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_200_OK)


__all__ = ["users_invite_resend", "users_invite_revoke", "users_invites"]


def _build_invites_list_payload(
    *,
    actor: InviteActor,
    limit: int,
    cursor: str | None,
) -> dict[str, object]:
    items, next_cursor, has_more = registration_lifecycle.list_pending_invites_page(
        actor=actor,
        limit=limit,
        cursor=cursor,
    )
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": bool(has_more),
        "total_returned": len(items),
        "total": len(items),
    }
