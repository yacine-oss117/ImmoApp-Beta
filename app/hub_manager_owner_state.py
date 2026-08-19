"""Hub Manager owner/admin state from Hub DB truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.hub_manager_access_client import (
    HubManagerAccessClientError,
    fetch_owner_state,
)

OWNER_ACCOUNT_MISSING = "owner_account_missing"
OWNER_ACTIVATION_PENDING = "owner_activation_pending"
OWNER_ACTIVE = "owner_active"
OWNER_STATES = {
    OWNER_ACCOUNT_MISSING,
    OWNER_ACTIVATION_PENDING,
    OWNER_ACTIVE,
}


@dataclass(frozen=True)
class HubOwnerState:
    state: str
    setup_available: bool
    activation_available: bool
    reason_code: str
    active_owner_admin_count: int = 0
    pending_registration_count: int = 0
    approved_registration_count: int = 0
    inactive_owner_count: int = 0

    @property
    def owner_active(self) -> bool:
        return self.state == OWNER_ACTIVE


def unavailable_owner_state(reason_code: str = "owner_state_unavailable") -> HubOwnerState:
    return HubOwnerState(
        state=OWNER_ACCOUNT_MISSING,
        setup_available=False,
        activation_available=False,
        reason_code=reason_code,
    )


def parse_hub_owner_state(payload: dict[str, Any] | None) -> HubOwnerState:
    if not isinstance(payload, dict):
        return unavailable_owner_state("owner_state_payload_missing")
    state = str(payload.get("state") or "").strip()
    if state not in OWNER_STATES:
        return unavailable_owner_state("owner_state_invalid")
    return HubOwnerState(
        state=state,
        setup_available=bool(payload.get("setup_available")),
        activation_available=bool(payload.get("activation_available")),
        reason_code=str(payload.get("reason_code") or ""),
        active_owner_admin_count=_int_payload(payload, "active_owner_admin_count"),
        pending_registration_count=_int_payload(payload, "pending_registration_count"),
        approved_registration_count=_int_payload(payload, "approved_registration_count"),
        inactive_owner_count=_int_payload(payload, "inactive_owner_count"),
    )


def resolve_hub_owner_state(base_url: str = "") -> HubOwnerState:
    """Resolve owner setup state through the running Hub front door."""

    if not base_url.strip():
        return unavailable_owner_state("owner_state_hub_connection_missing")
    try:
        return parse_hub_owner_state(fetch_owner_state(base_url))
    except HubManagerAccessClientError as exc:
        return unavailable_owner_state(exc.reason_code)


def _int_payload(payload: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(str(payload.get(key) or "0")))
    except ValueError:
        return 0


__all__ = [
    "HubOwnerState",
    "OWNER_ACCOUNT_MISSING",
    "OWNER_ACTIVATION_PENDING",
    "OWNER_ACTIVE",
    "parse_hub_owner_state",
    "resolve_hub_owner_state",
    "unavailable_owner_state",
]
