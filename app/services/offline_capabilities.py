from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OfflineCapability:
    supported: bool
    reason: str = ""


_DEFAULT_UNSUPPORTED = OfflineCapability(False, "This action requires an online connection.")

_CAPABILITIES: dict[tuple[str, str], OfflineCapability] = {
    ("client", "create"): OfflineCapability(True),
    ("demande", "create"): OfflineCapability(True),
    ("listing", "create"): OfflineCapability(True),
    ("offer", "create"): OfflineCapability(True),
    ("visit", "create"): OfflineCapability(True),
    ("contract", "create"): OfflineCapability(True),
    ("contract_article", "create"): OfflineCapability(True),
    ("contract_article", "update"): OfflineCapability(True),
    ("contract_article", "delete"): OfflineCapability(True),
    (
        "contract_article",
        "renumber",
    ): OfflineCapability(False, "Sync the contract first before working with articles."),
    (
        "contract_article",
        "copy_standard_clauses",
    ): OfflineCapability(False, "Sync the contract first before working with articles."),
    ("offer_photo", "create"): OfflineCapability(True),
    ("offer_photo", "upload"): OfflineCapability(True),
    ("offer_photo", "delete"): OfflineCapability(True),
    ("bulk_import", "execute"): OfflineCapability(False, "Imports require an online connection."),
}


def get_offline_capability(entity_type: str, action: str) -> OfflineCapability:
    key = (str(entity_type or "").strip().lower(), str(action or "").strip().lower())
    return _CAPABILITIES.get(key, _DEFAULT_UNSUPPORTED)


def require_supported_offline_action(entity_type: str, action: str) -> None:
    capability = get_offline_capability(entity_type, action)
    if not capability.supported:
        raise ValueError(capability.reason or _DEFAULT_UNSUPPORTED.reason)


__all__ = [
    "OfflineCapability",
    "get_offline_capability",
    "require_supported_offline_action",
]
