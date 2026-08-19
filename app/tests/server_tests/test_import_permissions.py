from __future__ import annotations

import pytest

from server.services.import_permissions import ImportPermissionError, validate_import_permissions


class _User:
    def __init__(self, *, role: str, can_import: bool) -> None:
        self.role = role
        self.can_import = can_import
        self.id = 1
        self.agency_id = 1
        self.is_superuser = role == "super_admin"


def test_import_permission_super_admin_allowed() -> None:
    validate_import_permissions(_User(role="super_admin", can_import=False))


def test_import_permission_manager_allowed() -> None:
    validate_import_permissions(_User(role="manager", can_import=False))


def test_import_permission_agent_requires_flag() -> None:
    with pytest.raises(ImportPermissionError):
        validate_import_permissions(_User(role="agent", can_import=False))
    validate_import_permissions(_User(role="agent", can_import=True))


def test_import_permission_unknown_role_rejected() -> None:
    with pytest.raises(ImportPermissionError):
        validate_import_permissions(_User(role="intern", can_import=True))
