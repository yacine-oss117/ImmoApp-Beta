"""
Permission checks and user protocol for import operations.
"""

from __future__ import annotations

from typing import Protocol


class UserProtocol(Protocol):
    id: int
    agency_id: int
    role: str
    is_superuser: bool
    can_import: bool


class ImportPermissionError(Exception):
    """Raised when user lacks import permission."""


ROLE_SUPER_ADMIN = "super_admin"
ROLE_MANAGER = "manager"
ROLE_AGENT = "agent"


def _has_effective_import_permission(user: UserProtocol) -> bool:
    if bool(getattr(user, "can_import", False)):
        return True
    if not hasattr(user, "_meta"):
        return False
    from server.services import permission_elevation

    return permission_elevation.has_effective_permission(user=user, permission="can_import")


def validate_import_permissions(user: UserProtocol) -> None:
    """Validate user has import permission."""
    if user.role == ROLE_SUPER_ADMIN:
        return
    if user.role == ROLE_MANAGER:
        return
    if user.role == ROLE_AGENT:
        if not _has_effective_import_permission(user):
            raise ImportPermissionError("Import permission required. Contact your manager.")
        return

    raise ImportPermissionError(f"Unknown role: {user.role}")
