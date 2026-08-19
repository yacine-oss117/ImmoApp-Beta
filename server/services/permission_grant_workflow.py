"""Mutation-side helpers for temporary privilege elevation workflow."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable, cast

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from server.accounts.models import PrivilegeElevationRequest
from server.services.errors import NotFoundError, PermissionDeniedError

from .permission_grant_queries import serialize_request_impl


def _int_attr(value: Any, name: str) -> int | None:
    raw = getattr(value, name, None)
    return int(raw) if raw is not None else None


def target_user_for_actor_impl(
    *,
    actor: Any,
    user_id: int,
    agency_id_of_fn: Callable[[Any], int | None],
    is_superuser_fn: Callable[[Any], bool],
    role_of_fn: Callable[[Any], str],
    is_owner_fn: Callable[[Any], bool],
) -> Any:
    User = get_user_model()
    target = User.objects.filter(id=int(user_id)).first()
    if target is None:
        raise NotFoundError("User not found.")
    if is_superuser_fn(actor):
        return target
    actor_agency_id = agency_id_of_fn(actor)
    if actor_agency_id is None or actor_agency_id != agency_id_of_fn(target):
        raise PermissionDeniedError("Forbidden agency scope.")
    if role_of_fn(actor) != "manager":
        raise PermissionDeniedError("Manager access required.")
    if is_owner_fn(actor):
        return target
    actor_id = getattr(actor, "id", None)
    if actor_id is None:
        raise PermissionDeniedError("Actor id required.")
    target_id = getattr(target, "id", None)
    if target_id is None:
        raise PermissionDeniedError("Target id required.")
    if int(target_id) == int(actor_id):
        return target
    if int(getattr(target, "manager_id", 0) or 0) != int(actor_id):
        raise PermissionDeniedError("Managers may only request elevation for self or owned agents.")
    return target


def require_owner_or_superuser_impl(
    *,
    actor: Any,
    is_superuser_fn: Callable[[Any], bool],
    role_of_fn: Callable[[Any], str],
    is_owner_fn: Callable[[Any], bool],
) -> None:
    if is_superuser_fn(actor):
        return
    if role_of_fn(actor) == "manager" and is_owner_fn(actor):
        return
    raise PermissionDeniedError("Owner access required.")


def request_elevation_impl(
    *,
    actor: Any,
    user_id: int,
    permission: str,
    reason: str | None,
    normalize_permission_fn: Callable[[str], str],
    agency_id_of_fn: Callable[[Any], int | None],
    is_superuser_fn: Callable[[Any], bool],
    role_of_fn: Callable[[Any], str],
    is_owner_fn: Callable[[Any], bool],
    require_manager_fn: Callable[[Any], None],
    auth_events_module: Any,
) -> dict[str, Any]:
    require_manager_fn(actor)
    target = target_user_for_actor_impl(
        actor=actor,
        user_id=user_id,
        agency_id_of_fn=agency_id_of_fn,
        is_superuser_fn=is_superuser_fn,
        role_of_fn=role_of_fn,
        is_owner_fn=is_owner_fn,
    )
    normalized_permission = normalize_permission_fn(permission)

    actor_id = getattr(actor, "id", None)
    target_id = getattr(target, "id", None)
    if target_id is None:
        raise PermissionDeniedError("Target id required.")
    with transaction.atomic():
        row = PrivilegeElevationRequest.objects.create(
            agency_id=agency_id_of_fn(target),
            user_id=int(target_id),
            permission=normalized_permission,
            reason=str(reason or "")[:512],
            requested_by_id=int(actor_id) if actor_id else None,
            status=PrivilegeElevationRequest.STATUS_PENDING,
        )

    auth_events_module.log_auth_event(
        event_type="privilege_elevation_requested",
        outcome="success",
        agency_id=agency_id_of_fn(target),
        user_id=int(target_id),
        identifier=str(getattr(target, "username", "") or ""),
        reason_code=normalized_permission,
        details={"request_id": _int_attr(row, "id")},
        fail_silently=True,
    )
    return serialize_request_impl(row)


def decide_request_impl(
    *,
    actor: Any,
    request_id: int,
    approve: bool,
    reason: str | None,
    duration_minutes: int | None,
    agency_id_of_fn: Callable[[Any], int | None],
    is_superuser_fn: Callable[[Any], bool],
    is_owner_fn: Callable[[Any], bool],
    role_of_fn: Callable[[Any], str],
    clamp_minutes_fn: Callable[[int | None], int],
    auth_events_module: Any,
    auth_security_alerts_module: Any,
) -> dict[str, Any]:
    require_owner_or_superuser_impl(
        actor=actor,
        is_superuser_fn=is_superuser_fn,
        role_of_fn=role_of_fn,
        is_owner_fn=is_owner_fn,
    )
    row = PrivilegeElevationRequest.objects.filter(id=int(request_id)).first()
    if row is None:
        raise NotFoundError("Privilege request not found.")
    row_agency_id = getattr(row, "agency_id", None)
    if not is_superuser_fn(actor) and agency_id_of_fn(actor) != row_agency_id:
        raise PermissionDeniedError("Forbidden agency scope.")
    if row.status != PrivilegeElevationRequest.STATUS_PENDING:
        raise ValueError("Privilege request is no longer pending.")

    now = timezone.now()
    row_id = getattr(row, "id", None)
    if row_id is None:
        raise NotFoundError("Privilege request not found.")
    with transaction.atomic():
        row = PrivilegeElevationRequest.objects.select_for_update().get(id=row_id)
        row_any = cast(Any, row)
        if row.status != PrivilegeElevationRequest.STATUS_PENDING:
            raise ValueError("Privilege request is no longer pending.")
        row.status = (
            PrivilegeElevationRequest.STATUS_APPROVED
            if approve
            else PrivilegeElevationRequest.STATUS_DENIED
        )
        row_any.approved_by_id = getattr(actor, "id", None)
        row.decided_at = now
        if approve:
            ttl_minutes = clamp_minutes_fn(duration_minutes)
            row.expires_at = now + timedelta(minutes=ttl_minutes)
        else:
            row.expires_at = None
            row.revoke_reason = str(reason or "")[:256]
        row.save(
            update_fields=[
                "status",
                "approved_by",
                "decided_at",
                "expires_at",
                "revoke_reason",
            ]
        )

    auth_events_module.log_auth_event(
        event_type="privilege_elevation_approved" if approve else "privilege_elevation_denied",
        outcome="success",
        agency_id=getattr(row, "agency_id", None),
        user_id=getattr(row, "user_id", None),
        identifier=str(getattr(row.user, "username", "") or ""),
        reason_code=row.permission,
        details={"request_id": _int_attr(row, "id")},
        fail_silently=True,
    )
    if approve:
        row_agency_id = getattr(row, "agency_id", None)
        row_user_id = getattr(row, "user_id", None)
        row_id = getattr(row, "id", None)
        auth_security_alerts_module.emit_security_alert(
            reason_code="privilege_spike",
            agency_id=row_agency_id,
            user_id=row_user_id,
            identifier=str(getattr(row.user, "username", "") or ""),
            source_ip=None,
            details={
                "permission": row.permission,
                "request_id": int(row_id) if row_id is not None else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            },
            cooldown_identity=f"{row_agency_id}:{row_user_id}:{row.permission}",
        )
    return serialize_request_impl(row)


def revoke_request_impl(
    *,
    actor: Any,
    request_id: int,
    reason: str | None,
    agency_id_of_fn: Callable[[Any], int | None],
    is_superuser_fn: Callable[[Any], bool],
    is_owner_fn: Callable[[Any], bool],
    role_of_fn: Callable[[Any], str],
    auth_events_module: Any,
) -> dict[str, Any]:
    require_owner_or_superuser_impl(
        actor=actor,
        is_superuser_fn=is_superuser_fn,
        role_of_fn=role_of_fn,
        is_owner_fn=is_owner_fn,
    )
    row = PrivilegeElevationRequest.objects.filter(id=int(request_id)).first()
    if row is None:
        raise NotFoundError("Privilege request not found.")
    if not is_superuser_fn(actor) and agency_id_of_fn(actor) != getattr(row, "agency_id", None):
        raise PermissionDeniedError("Forbidden agency scope.")
    if row.status == PrivilegeElevationRequest.STATUS_REVOKED:
        return serialize_request_impl(row)
    row_id = getattr(row, "id", None)
    if row_id is None:
        raise NotFoundError("Privilege request not found.")
    with transaction.atomic():
        row = PrivilegeElevationRequest.objects.select_for_update().get(id=row_id)
        row_any = cast(Any, row)
        row.status = PrivilegeElevationRequest.STATUS_REVOKED
        row.revoked_at = timezone.now()
        row_any.revoked_by_id = getattr(actor, "id", None)
        row.revoke_reason = str(reason or "revoked")[:256]
        row.save(update_fields=["status", "revoked_at", "revoked_by", "revoke_reason"])
    auth_events_module.log_auth_event(
        event_type="privilege_elevation_revoked",
        outcome="success",
        agency_id=getattr(row, "agency_id", None),
        user_id=getattr(row, "user_id", None),
        identifier=str(getattr(row.user, "username", "") or ""),
        reason_code=row.permission,
        details={"request_id": _int_attr(row, "id")},
        fail_silently=True,
    )
    return serialize_request_impl(row)
