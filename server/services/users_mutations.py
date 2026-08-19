"""User service mutation operations."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from core.data.surface_cache_generation import (
    USERS_SURFACE,
    agency_scope_key,
)
from server.services import auth_events, auth_security_alerts, auth_sessions
from server.services.accounts_ale import apply_user_ale
from server.services.errors import NotFoundError, PermissionDeniedError
from server.services.surface_cache_generations import bump_generation_in_atomic

from .users_helpers import (
    agency_id_of,
    apply_user_fields,
    ensure_manager_is_owner,
    ensure_manager_owns_agent,
    ensure_manager_target_role,
    ensure_role_allowed,
    get_user_model_for_service,
    is_superuser,
    normalize_role,
    require_manager,
    require_owner,
    require_same_agency,
    resolve_manager_id,
    serialize_user,
    validate_manager_assignment,
)
from .users_types import UserCreateInput, UserUpdateInput


def _bump_users_surface_generation(*, agency_id: int | None) -> None:
    if not isinstance(agency_id, int) or agency_id <= 0:
        return
    bump_generation_in_atomic(
        surface=USERS_SURFACE,
        scope_key=agency_scope_key(agency_id),
        agency_id=agency_id,
    )


def _emit_privilege_spike_alert(
    *, actor: object | None, user: object, details: dict[str, object]
) -> None:
    auth_security_alerts.emit_security_alert(
        reason_code="privilege_spike",
        agency_id=agency_id_of(user),
        user_id=int(getattr(user, "id", 0) or 0),
        identifier=str(getattr(user, "username", "") or ""),
        source_ip=None,
        details={
            "actor_id": getattr(actor, "id", None),
            **details,
        },
        cooldown_identity=f"{agency_id_of(user)}:{getattr(user, 'id', None)}:direct-mutation",
    )


def create_user(
    *,
    actor: object | None,
    data: UserCreateInput,
) -> dict[str, object]:
    require_manager(actor)
    User = get_user_model_for_service()
    role = normalize_role(str(data.get("role") or ""))
    ensure_role_allowed(actor, role)

    actor_agency_id = agency_id_of(actor)
    agency_id = int(data.get("agency_id") or 0) if data.get("agency_id") else None
    if not is_superuser(actor):
        agency_id = actor_agency_id
    if agency_id is None:
        raise PermissionDeniedError("Agency is required.")

    manager_id = data.get("manager_id")
    if role == "manager":
        manager_id = None
    else:
        manager_id = resolve_manager_id(
            actor=actor,
            desired_manager_id=manager_id if manager_id is not None else None,
            agency_id=agency_id,
        )
        if manager_id is None:
            raise PermissionDeniedError("Agent must have a manager.")
        manager_id = validate_manager_assignment(manager_id, agency_id=agency_id)

    if data.get("is_owner"):
        ensure_manager_is_owner(actor, field="is_owner")

    if data.get("can_hard_delete"):
        ensure_manager_is_owner(actor, field="can_hard_delete")

    payload = {
        "username": str(data.get("username") or ""),
        "email": str(data.get("email") or ""),
        "first_name": str(data.get("first_name") or ""),
        "last_name": str(data.get("last_name") or ""),
        "role": role,
        "is_owner": bool(data.get("is_owner", False)),
        "is_active": bool(data.get("is_active", True)),
        "can_import": bool(data.get("can_import", False)),
        "can_hard_delete": bool(data.get("can_hard_delete", False)),
        "agency_id": agency_id,
        "manager_id": manager_id,
    }
    apply_user_ale(payload, changed_fields=set(payload.keys()))
    password = str(data.get("password") or "")
    if not password:
        raise ValueError("password is required")

    with transaction.atomic():
        user = User(**payload)
        if password:
            user.set_password(password)
        if user.role == "agent" and user.can_import:
            user.import_granted_by = actor if actor else None
        if user.role == "manager":
            user.import_granted_by = None
        try:
            user.full_clean()
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        user.save()
        _bump_users_surface_generation(agency_id=agency_id_of(user))
    if (
        role in {"manager", "super_admin"}
        or bool(payload["is_owner"])
        or bool(payload["can_hard_delete"])
    ):
        _emit_privilege_spike_alert(
            actor=actor,
            user=user,
            details={
                "change_type": "create_user",
                "role": role,
                "is_owner": bool(payload["is_owner"]),
                "can_hard_delete": bool(payload["can_hard_delete"]),
                "can_import": bool(payload["can_import"]),
            },
        )
    return serialize_user(user)


def update_user(
    *,
    actor: object | None,
    user_id: int,
    data: UserUpdateInput,
) -> dict[str, object]:
    require_manager(actor)
    User = get_user_model_for_service()
    user = User.objects.filter(id=user_id).first()
    if not user:
        raise NotFoundError("User not found.")
    require_same_agency(actor, user)
    ensure_manager_target_role(actor, user)
    ensure_manager_owns_agent(actor, user)

    if "role" in data:
        ensure_role_allowed(actor, str(data.get("role") or ""))
    if "is_owner" in data:
        ensure_manager_is_owner(actor, field="is_owner")
    if "can_hard_delete" in data:
        ensure_manager_is_owner(actor, field="can_hard_delete")

    if "agency_id" in data and not is_superuser(actor):
        raise PermissionDeniedError("Only superusers can change agency.")

    role = str(data.get("role") or getattr(user, "role", "agent"))
    manager_id = (
        data.get("manager_id") if "manager_id" in data else getattr(user, "manager_id", None)
    )
    if role == "manager":
        manager_id = None
    else:
        manager_id = resolve_manager_id(
            actor=actor,
            desired_manager_id=manager_id,
            agency_id=agency_id_of(user),
        )
        if manager_id is None:
            raise PermissionDeniedError("Agent must have a manager.")
        manager_id = validate_manager_assignment(manager_id, agency_id=agency_id_of(user))

    updates: dict[str, object] = {}
    for key in ("email", "first_name", "last_name", "is_active", "can_import", "can_hard_delete"):
        if key in data:
            updates[key] = data[key]
    updates["role"] = role
    updates["manager_id"] = manager_id
    if "is_owner" in data:
        updates["is_owner"] = bool(data.get("is_owner"))
    if "agency_id" in data and is_superuser(actor):
        updates["agency_id"] = data.get("agency_id")
    apply_user_ale(updates, changed_fields=set(updates.keys()))

    with transaction.atomic():
        previous_agency_id = agency_id_of(user)
        before = {
            "role": str(getattr(user, "role", "") or ""),
            "is_owner": bool(getattr(user, "is_owner", False)),
            "can_hard_delete": bool(getattr(user, "can_hard_delete", False)),
            "can_import": bool(getattr(user, "can_import", False)),
            "is_active": bool(getattr(user, "is_active", False)),
        }
        apply_user_fields(user, updates)
        password_changed = False
        if "password" in data:
            if isinstance(data.get("password"), str) and data.get("password"):
                user.set_password(str(data.get("password")))
                password_changed = True
        if getattr(user, "role", None) == "agent" and getattr(user, "can_import", False):
            user.import_granted_by = actor if actor else None
        if getattr(user, "role", None) == "manager":
            user.import_granted_by = None
        try:
            user.full_clean()
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        user.save()
        if before["is_active"] and not bool(getattr(user, "is_active", False)):
            auth_sessions.revoke_user_sessions(user=user, reason="user_deactivated")
        _bump_users_surface_generation(agency_id=previous_agency_id)
        _bump_users_surface_generation(agency_id=agency_id_of(user))
    after = {
        "role": str(getattr(user, "role", "") or ""),
        "is_owner": bool(getattr(user, "is_owner", False)),
        "can_hard_delete": bool(getattr(user, "can_hard_delete", False)),
        "can_import": bool(getattr(user, "can_import", False)),
    }
    privilege_escalated = (
        (before["role"] != after["role"] and after["role"] in {"manager", "super_admin"})
        or (not before["is_owner"] and after["is_owner"])
        or (not before["can_hard_delete"] and after["can_hard_delete"])
        or (not before["can_import"] and after["can_import"])
    )
    if privilege_escalated:
        _emit_privilege_spike_alert(
            actor=actor,
            user=user,
            details={
                "change_type": "update_user",
                "before": before,
                "after": after,
            },
        )
    if password_changed:
        auth_events.log_auth_event(
            event_type="password_change",
            outcome="success",
            agency_id=agency_id_of(user),
            user_id=int(user.id),
            identifier=str(getattr(user, "username", "") or ""),
            reason_code="updated_by_manager",
            fail_silently=True,
        )
    return serialize_user(user)


def deactivate_user(
    *,
    actor: object | None,
    user_id: int,
) -> None:
    require_owner(actor)
    User = get_user_model_for_service()
    user = User.objects.filter(id=user_id).first()
    if not user:
        raise NotFoundError("User not found.")
    require_same_agency(actor, user)
    if getattr(actor, "id", None) == getattr(user, "id", None):
        raise PermissionDeniedError("You cannot deactivate yourself.")
    user.is_active = False
    with transaction.atomic():
        user.full_clean()
        user.save(update_fields=["is_active"])
        auth_sessions.revoke_user_sessions(user=user, reason="user_deactivated")
        _bump_users_surface_generation(agency_id=agency_id_of(user))


__all__ = ["create_user", "deactivate_user", "update_user"]
