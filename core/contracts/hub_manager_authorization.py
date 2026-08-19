"""Shared Hub Manager protected-action authorization contract."""

from __future__ import annotations

from types import MappingProxyType

DELETE_HUB_DATA_ACTION = "delete_hub_data"
HUB_MANAGER_PROTECTED_SCOPE = "hub_manager_protected_action"
HUB_DATA_DELETE_SCOPE = "hub_data_delete"

PROTECTED_ACTION_SCOPES = MappingProxyType(
    {
        DELETE_HUB_DATA_ACTION: HUB_DATA_DELETE_SCOPE,
        "finish-hub-setup": HUB_MANAGER_PROTECTED_SCOPE,
        "rename-hub": HUB_MANAGER_PROTECTED_SCOPE,
        "install-runtime-candidate": HUB_MANAGER_PROTECTED_SCOPE,
        "install-runtime-artifact": HUB_MANAGER_PROTECTED_SCOPE,
        "remove-runtime-candidate": HUB_MANAGER_PROTECTED_SCOPE,
        "cleanup-runtime-logs": HUB_MANAGER_PROTECTED_SCOPE,
        "backup-now": HUB_MANAGER_PROTECTED_SCOPE,
        "logs": HUB_MANAGER_PROTECTED_SCOPE,
    }
)
PROTECTED_ACTIONS = frozenset(PROTECTED_ACTION_SCOPES)


def authorization_scope(action: str) -> str:
    """Return the required scope for a protected Hub Manager action."""

    try:
        return PROTECTED_ACTION_SCOPES[action]
    except KeyError as exc:
        raise ValueError("hub_owner_authorization_wrong_action") from exc


__all__ = [
    "DELETE_HUB_DATA_ACTION",
    "HUB_DATA_DELETE_SCOPE",
    "HUB_MANAGER_PROTECTED_SCOPE",
    "PROTECTED_ACTION_SCOPES",
    "PROTECTED_ACTIONS",
    "authorization_scope",
]
