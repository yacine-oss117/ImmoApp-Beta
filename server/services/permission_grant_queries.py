"""Read-side helpers for temporary privilege elevation state."""

from __future__ import annotations

from typing import Any, Callable, cast

from django.db.models import Q
from django.utils import timezone

from server.accounts.models import PrivilegeElevationRequest


def _optional_int_attr(row: Any, name: str) -> int | None:
    value = getattr(row, name, None)
    return int(value) if value is not None else None


def serialize_request_impl(row: Any) -> dict[str, Any]:
    row_any = cast(Any, row)
    now = timezone.now()
    is_active = (
        row_any.status == PrivilegeElevationRequest.STATUS_APPROVED
        and row_any.revoked_at is None
        and (row_any.expires_at is None or row_any.expires_at > now)
    )
    if row_any.status == PrivilegeElevationRequest.STATUS_APPROVED and not is_active:
        effective_status = "expired"
    else:
        effective_status = row_any.status
    return {
        "id": int(row_any.id),
        "agency_id": int(row_any.agency_id),
        "user_id": int(row_any.user_id),
        "permission": str(row_any.permission),
        "reason": str(row_any.reason or ""),
        "status": effective_status,
        "requested_by": _optional_int_attr(row_any, "requested_by_id"),
        "approved_by": _optional_int_attr(row_any, "approved_by_id"),
        "revoked_by": _optional_int_attr(row_any, "revoked_by_id"),
        "requested_at": row_any.requested_at.isoformat() if row_any.requested_at else None,
        "decided_at": row_any.decided_at.isoformat() if row_any.decided_at else None,
        "expires_at": row_any.expires_at.isoformat() if row_any.expires_at else None,
        "revoked_at": row_any.revoked_at.isoformat() if row_any.revoked_at else None,
        "revoke_reason": str(row_any.revoke_reason or ""),
        "is_active": bool(is_active),
    }


def list_requests_impl(
    *,
    actor: Any,
    user_id: int | None = None,
    status: str | None = None,
    agency_id_of_fn: Callable[[Any], int | None],
    is_owner_fn: Callable[[Any], bool],
    is_superuser_fn: Callable[[Any], bool],
    require_manager_fn: Callable[[Any], None],
) -> list[dict[str, Any]]:
    require_manager_fn(actor)
    qs = PrivilegeElevationRequest.objects.select_related("user").order_by("-requested_at", "-id")
    if is_superuser_fn(actor):
        pass
    else:
        actor_agency_id = agency_id_of_fn(actor)
        qs = qs.filter(agency_id=actor_agency_id)
        if not is_owner_fn(actor):
            actor_id = getattr(actor, "id", None)
            qs = qs.filter(Q(user__manager_id=actor_id) | Q(user_id=actor_id))
    if user_id is not None:
        qs = qs.filter(user_id=int(user_id))
    status_filter = str(status or "").strip().lower()
    if status_filter:
        if status_filter == "expired":
            now = timezone.now()
            qs = qs.filter(
                status=PrivilegeElevationRequest.STATUS_APPROVED,
                revoked_at__isnull=True,
                expires_at__lte=now,
            )
        else:
            qs = qs.filter(status=status_filter)
    return [serialize_request_impl(row) for row in qs[:500]]


def has_effective_permission_impl(
    *,
    user: Any,
    permission: str,
    normalize_permission_fn: Callable[[str], str],
    is_superuser_fn: Callable[[Any], bool],
) -> bool:
    normalized = normalize_permission_fn(permission)
    if not hasattr(user, "_meta"):
        return bool(getattr(user, normalized, False))
    if is_superuser_fn(user):
        return True
    if bool(getattr(user, normalized, False)):
        return True
    user_id = getattr(user, "id", None)
    if user_id is None:
        return False
    now = timezone.now()
    return bool(
        PrivilegeElevationRequest.objects.filter(
            user_id=user_id,
            permission=normalized,
            status=PrivilegeElevationRequest.STATUS_APPROVED,
            revoked_at__isnull=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .exists()
    )


def list_effective_permissions_impl(
    *,
    user: Any,
    permissions: set[str],
    normalize_permission_fn: Callable[[str], str],
    is_superuser_fn: Callable[[Any], bool],
) -> dict[str, bool]:
    return {
        permission: has_effective_permission_impl(
            user=user,
            permission=permission,
            normalize_permission_fn=normalize_permission_fn,
            is_superuser_fn=is_superuser_fn,
        )
        for permission in sorted(permissions)
    }
