from __future__ import annotations

import pytest

from app import hub_manager_owner_state as module
from app.hub_manager_owner_state import (
    OWNER_ACCOUNT_MISSING,
    OWNER_ACTIVE,
    parse_hub_owner_state,
    resolve_hub_owner_state,
)


def test_parse_hub_owner_state_accepts_non_secret_counts() -> None:
    state = parse_hub_owner_state(
        {
            "state": OWNER_ACTIVE,
            "setup_available": True,
            "activation_available": False,
            "reason_code": "active_owner_admin_exists",
            "active_owner_admin_count": 2,
        }
    )

    assert state.owner_active
    assert state.setup_available
    assert not state.activation_available
    assert state.active_owner_admin_count == 2


def test_parse_hub_owner_state_fails_closed_for_unknown_state() -> None:
    state = parse_hub_owner_state({"state": "employee_active", "setup_available": True})

    assert state.state == OWNER_ACCOUNT_MISSING
    assert not state.setup_available
    assert state.reason_code == "owner_state_invalid"


def test_resolve_hub_owner_state_uses_hub_front_door_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_fetch(base_url: str) -> dict[str, object]:
        calls.append(base_url)
        return {
            "state": OWNER_ACCOUNT_MISSING,
            "setup_available": True,
            "activation_available": False,
            "reason_code": "owner_account_missing",
        }

    monkeypatch.setattr(module, "fetch_owner_state", fake_fetch)
    state = resolve_hub_owner_state("http://127.0.0.1:18001")

    assert state.state == OWNER_ACCOUNT_MISSING
    assert state.setup_available
    assert calls == ["http://127.0.0.1:18001"]
