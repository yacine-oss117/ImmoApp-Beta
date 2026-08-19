"""User service helpers for RBAC and validation."""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth import get_user_model

from server.services.accounts_ale import resolve_user_name
from server.services.errors import NotFoundError, PermissionDeniedError


def get_user_model_for_service() -> Any:
    return get_user_model()


def is_superuser(user: object | None) -> bool:
    return bool(user and getattr(user, "is_superuser", False))


def is_owner(user: object | None) -> bool:
    return bool(user and getattr(user, "is_owner", False))


def role_of(user: object | None) -> str | None:
    role = getattr(user, "role", None) if user else None
    return str(role) if isinstance(role, str) and role else None


def agency_id_of(user: object | None) -> int | None:
    if not user:
        return None
    agency_id = getattr(user, "agency_id", None)
    if agency_id is None:
        agency = getattr(user, "agency", None)
        agency_id = getattr(agency, "id", None) if agency else None
    return int(agency_id) if agency_id is not None else None


def require_manager(actor: object | None) -> None:
    if is_superuser(actor):
        return
    if role_of(actor) != "manager":
        raise PermissionDeniedError("Manager access required.")


def require_owner(actor: object | None) -> None:
    if is_superuser(actor):
        return
    if role_of(actor) == "manager" and is_owner(actor):
        return
    raise PermissionDeniedError("Owner access required.")


def normalize_role(role: str | None) -> str:
    if not role:
        return "agent"
    return role


def ensure_role_allowed(actor: object | None, role: str) -> None:
    if is_superuser(actor):
        return
    if role == "super_admin":
        raise PermissionDeniedError("Only superusers can assign super_admin role.")
    if is_owner(actor):
        if role not in {"manager", "agent"}:
            raise PermissionDeniedError("Owner can only assign manager or agent roles.")
        return
    if role != "agent":
        raise PermissionDeniedError("Managers may only create or update agents.")


def require_same_agency(actor: object | None, target: object) -> None:
    if is_superuser(actor):
        return
    actor_agency_id = agency_id_of(actor)
    target_agency_id = agency_id_of(target)
    if actor_agency_id is None or target_agency_id is None or actor_agency_id != target_agency_id:
        raise PermissionDeniedError("User is outside your agency.")


def ensure_manager_is_owner(actor: object | None, *, field: str) -> None:
    if is_superuser(actor):
        return
    if is_owner(actor):
        return
    raise PermissionDeniedError(f"Only an agency owner can modify {field}.")


def ensure_manager_owns_agent(actor: object | None, target: object) -> None:
    if is_superuser(actor) or is_owner(actor):
        return
    actor_id = getattr(actor, "id", None)
    if actor_id is None:
        raise PermissionDeniedError("Actor id required.")
    if getattr(target, "manager_id", None) != actor_id:
        raise PermissionDeniedError("Managers may only manage their own agents.")


def ensure_manager_target_role(actor: object | None, target: object) -> None:
    if is_superuser(actor) or is_owner(actor):
        return
    if getattr(target, "role", None) != "agent":
        raise PermissionDeniedError("Managers may only manage agents.")


def resolve_manager_id(
    *,
    actor: object | None,
    desired_manager_id: int | None,
    agency_id: int | None,
) -> int | None:
    if is_superuser(actor):
        return desired_manager_id
    if is_owner(actor):
        return desired_manager_id
    actor_id = getattr(actor, "id", None)
    return int(actor_id) if actor_id is not None else None


def validate_manager_assignment(
    manager_id: int | None,
    *,
    agency_id: int | None,
) -> int | None:
    if manager_id is None:
        return None
    User = get_user_model_for_service()
    manager = User.objects.filter(id=manager_id).first()
    if not manager:
        raise NotFoundError("Manager not found.")
    if getattr(manager, "role", None) != "manager":
        raise ValueError("Assigned manager must have role manager.")
    if agency_id is not None and agency_id_of(manager) != agency_id:
        raise PermissionDeniedError("Manager must belong to the same agency.")
    return int(manager_id)


def apply_user_fields(user: object, data: dict[str, object]) -> None:
    user_obj = cast(Any, user)
    for key, value in data.items():
        if key == "password":
            if isinstance(value, str) and value:
                user_obj.set_password(value)
            continue
        setattr(user_obj, key, value)


def serialize_user(user: object) -> dict[str, object]:
    user_obj = cast(Any, user)
    first_name = resolve_user_name(user_obj, "first_name")
    last_name = resolve_user_name(user_obj, "last_name")
    return {
        "id": int(user_obj.id),
        "username": str(user_obj.username or ""),
        "email": str(user_obj.email or ""),
        "first_name": first_name,
        "last_name": last_name,
        "role": str(user_obj.role or ""),
        "is_owner": bool(user_obj.is_owner),
        "manager_id": user_obj.manager_id,
        "agency_id": user_obj.agency_id,
        "is_active": bool(user_obj.is_active),
        "can_import": bool(user_obj.can_import),
        "can_hard_delete": bool(user_obj.can_hard_delete),
        "last_login": str(user_obj.last_login or ""),
        "date_joined": str(user_obj.date_joined or ""),
    }


__all__ = [
    "apply_user_fields",
    "agency_id_of",
    "ensure_manager_is_owner",
    "ensure_manager_owns_agent",
    "ensure_manager_target_role",
    "ensure_role_allowed",
    "get_user_model_for_service",
    "is_owner",
    "is_superuser",
    "normalize_role",
    "require_manager",
    "require_owner",
    "require_same_agency",
    "resolve_manager_id",
    "role_of",
    "serialize_user",
    "validate_manager_assignment",
]
