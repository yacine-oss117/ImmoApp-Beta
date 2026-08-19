"""Temporary privilege elevation workflow with approval and expiry."""

from __future__ import annotations

import os
from typing import Any

from server.accounts.models import PrivilegeElevationRequest
from server.services import (
    auth_events,
    auth_security_alerts,
    permission_grant_queries,
    permission_grant_workflow,
)
from server.services.users_helpers import (
    agency_id_of,
    is_owner,
    is_superuser,
    require_manager,
    role_of,
)

_SUPPORTED_PERMISSIONS = {
    PrivilegeElevationRequest.PERMISSION_CAN_IMPORT,
    PrivilegeElevationRequest.PERMISSION_CAN_HARD_DELETE,
}


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


_DEFAULT_APPROVAL_MINUTES = _int_env(
    "IMMOAPP_PRIVILEGE_ELEVATION_DEFAULT_MINUTES",
    120,
    low=5,
    high=24 * 60,
)
_MAX_APPROVAL_MINUTES = _int_env(
    "IMMOAPP_PRIVILEGE_ELEVATION_MAX_MINUTES",
    24 * 60,
    low=5,
    high=7 * 24 * 60,
)


def _role_of_or_empty(user: object | None) -> str:
    return role_of(user) or ""


def _normalize_permission(permission: str) -> str:
    value = str(permission or "").strip()
    if value not in _SUPPORTED_PERMISSIONS:
        raise ValueError(f"Unsupported permission '{value}'")
    return value


def _clamp_minutes(value: int | None) -> int:
    if value is None:
        return _DEFAULT_APPROVAL_MINUTES
    return max(5, min(int(value), _MAX_APPROVAL_MINUTES))


def request_elevation(
    *,
    actor: object | None,
    user_id: int,
    permission: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return permission_grant_workflow.request_elevation_impl(
        actor=actor,
        user_id=user_id,
        permission=permission,
        reason=reason,
        normalize_permission_fn=_normalize_permission,
        agency_id_of_fn=agency_id_of,
        is_superuser_fn=is_superuser,
        role_of_fn=_role_of_or_empty,
        is_owner_fn=is_owner,
        require_manager_fn=require_manager,
        auth_events_module=auth_events,
    )


def list_requests(
    *,
    actor: object | None,
    user_id: int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    return permission_grant_queries.list_requests_impl(
        actor=actor,
        user_id=user_id,
        status=status,
        agency_id_of_fn=agency_id_of,
        is_owner_fn=is_owner,
        is_superuser_fn=is_superuser,
        require_manager_fn=require_manager,
    )


def decide_request(
    *,
    actor: object | None,
    request_id: int,
    approve: bool,
    reason: str | None = None,
    duration_minutes: int | None = None,
) -> dict[str, Any]:
    return permission_grant_workflow.decide_request_impl(
        actor=actor,
        request_id=request_id,
        approve=approve,
        reason=reason,
        duration_minutes=duration_minutes,
        agency_id_of_fn=agency_id_of,
        is_superuser_fn=is_superuser,
        is_owner_fn=is_owner,
        role_of_fn=_role_of_or_empty,
        clamp_minutes_fn=_clamp_minutes,
        auth_events_module=auth_events,
        auth_security_alerts_module=auth_security_alerts,
    )


def revoke_request(
    *,
    actor: object | None,
    request_id: int,
    reason: str | None = None,
) -> dict[str, Any]:
    return permission_grant_workflow.revoke_request_impl(
        actor=actor,
        request_id=request_id,
        reason=reason,
        agency_id_of_fn=agency_id_of,
        is_superuser_fn=is_superuser,
        is_owner_fn=is_owner,
        role_of_fn=_role_of_or_empty,
        auth_events_module=auth_events,
    )


def has_effective_permission(*, user: object | None, permission: str) -> bool:
    return permission_grant_queries.has_effective_permission_impl(
        user=user,
        permission=permission,
        normalize_permission_fn=_normalize_permission,
        is_superuser_fn=is_superuser,
    )


def list_effective_permissions(*, user: object | None) -> dict[str, bool]:
    return permission_grant_queries.list_effective_permissions_impl(
        user=user,
        permissions=_SUPPORTED_PERMISSIONS,
        normalize_permission_fn=_normalize_permission,
        is_superuser_fn=is_superuser,
    )


__all__ = [
    "decide_request",
    "has_effective_permission",
    "list_effective_permissions",
    "list_requests",
    "request_elevation",
    "revoke_request",
]
