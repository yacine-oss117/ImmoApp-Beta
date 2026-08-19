"""RBAC helpers for API views."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from server.services import permission_elevation

from .view_helpers import error


def _user(request: Request) -> Any | None:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return user
    return None


def _role(request: Request) -> str | None:
    user = _user(request)
    role = getattr(user, "role", None) if user else None
    return str(role) if isinstance(role, str) and role else None


def _is_superuser(request: Request) -> bool:
    user = _user(request)
    return bool(user and getattr(user, "is_superuser", False))


def _is_owner(request: Request) -> bool:
    user = _user(request)
    return bool(user and getattr(user, "is_owner", False))


def _can_hard_delete(request: Request) -> bool:
    user = _user(request)
    if not user:
        return False
    return permission_elevation.has_effective_permission(
        user=user,
        permission="can_hard_delete",
    )


def require_superuser(request: Request) -> Response | None:
    """Require a superuser."""
    if _is_superuser(request):
        return None
    return error("Forbidden", status.HTTP_403_FORBIDDEN)


def require_manager(request: Request) -> Response | None:
    """Require manager or superuser."""
    if _is_superuser(request):
        return None
    if _is_owner(request):
        return None
    if _role(request) == "manager":
        return None
    return error("Forbidden", status.HTTP_403_FORBIDDEN)


def require_owner(request: Request) -> Response | None:
    """Require agency owner or superuser."""
    if _is_superuser(request):
        return None
    if _is_owner(request):
        return None
    return error("Forbidden", status.HTTP_403_FORBIDDEN)


def require_hard_delete(request: Request) -> Response | None:
    """Require hard delete permission (manager with can_hard_delete or superuser)."""
    if _is_superuser(request):
        return None
    if _role(request) == "manager" and _can_hard_delete(request):
        return None
    return error("Forbidden", status.HTTP_403_FORBIDDEN)


__all__ = [
    "require_hard_delete",
    "require_manager",
    "require_owner",
    "require_superuser",
]
