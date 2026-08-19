from __future__ import annotations

import os
from dataclasses import dataclass

import pytest


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    os.environ.setdefault("DJANGO_SECRET_KEY", "hub-manager-access-contract-secret")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


class _MemoryGrantCache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def add(self, key: str, value: object, timeout: int) -> bool:
        del timeout
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> object | None:
        return self.values.get(key)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


@dataclass
class _Actor:
    pk: int = 42
    agency_id: int = 7
    role: str = "manager"
    is_active: bool = True
    is_owner: bool = True
    can_hard_delete: bool = False
    is_superuser: bool = False


class _UserQuery:
    def __init__(self, actor: _Actor | None) -> None:
        self._actor = actor

    def first(self) -> _Actor | None:
        return self._actor


class _UserManager:
    def __init__(self, actor: _Actor | None) -> None:
        self._actor = actor

    def filter(self, **_kwargs: object) -> _UserQuery:
        return _UserQuery(self._actor)


def _binding() -> dict[str, str]:
    return {
        "hub_id": "hub-123",
        "hub_display_name": "Main Office",
        "hub_identity_sha256": "a" * 64,
        "hub_state_manifest_sha256": "b" * 64,
        "hub_state_install_lineage": "lineage-123",
    }


@pytest.mark.parametrize(
    ("counts", "expected_state", "setup_available", "activation_available", "reason_code"),
    [
        (
            {},
            "owner_account_missing",
            True,
            False,
            "owner_account_missing",
        ),
        (
            {"platform_admin_configured": False},
            "owner_account_missing",
            False,
            False,
            "platform_admin_email_missing",
        ),
        (
            {"pending_registration_count": 1},
            "owner_activation_pending",
            True,
            False,
            "registration_pending_platform_approval",
        ),
        (
            {"approved_registration_count": 1, "inactive_owner_count": 1},
            "owner_activation_pending",
            True,
            True,
            "approved_inactive_owner_exists",
        ),
        (
            {"approved_registration_count": 1},
            "owner_activation_pending",
            True,
            False,
            "registration_approved_without_inactive_owner",
        ),
        (
            {"active_owner_admin_count": 1},
            "owner_active",
            True,
            False,
            "active_owner_admin_exists",
        ),
    ],
)
def test_owner_state_invariants(
    counts: dict[str, object],
    expected_state: str,
    setup_available: bool,
    activation_available: bool,
    reason_code: str,
) -> None:
    _ensure_django()
    from server.services import hub_manager_access

    inputs = {
        "platform_admin_configured": True,
        "active_owner_admin_count": 0,
        "pending_registration_count": 0,
        "approved_registration_count": 0,
        "inactive_owner_count": 0,
        **counts,
    }
    state = hub_manager_access._owner_state_from_counts(**inputs)

    assert state["state"] == expected_state
    assert state["setup_available"] is setup_available
    assert state["activation_available"] is activation_available
    assert state["reason_code"] == reason_code


@pytest.mark.parametrize(
    ("actor", "expected_role"),
    [
        (_Actor(is_owner=True), "agency_owner"),
        (_Actor(is_owner=False, can_hard_delete=True), "agency_admin"),
        (_Actor(role="super_admin", is_owner=False, is_superuser=True), "agency_admin"),
    ],
)
def test_hub_issues_one_use_authorization_only_for_active_owner_admin(
    monkeypatch: pytest.MonkeyPatch,
    actor: _Actor,
    expected_role: str,
) -> None:
    _ensure_django()
    from server.services import hub_manager_access

    grant_cache = _MemoryGrantCache()
    monkeypatch.setattr(hub_manager_access, "cache", grant_cache)
    user_model = type("UserModel", (), {"objects": _UserManager(actor)})
    monkeypatch.setattr(hub_manager_access, "get_user_model", lambda: user_model)

    evidence = hub_manager_access.issue_authorization(
        actor=actor,
        action="backup-now",
        hub_binding=_binding(),
    )

    assert evidence["schema_version"] == 3
    assert evidence["proof_result"] == "GO"
    assert evidence["authorized_role"] == expected_role
    assert evidence["plaintext_password_written"] is False
    assert evidence["session_token_written"] is False
    assert "username" not in evidence
    assert "email" not in evidence

    consumed = hub_manager_access.consume_authorization(
        nonce=str(evidence["evidence_nonce"]),
        action="backup-now",
        hub_id="hub-123",
    )
    assert consumed["proof_result"] == "GO"

    with pytest.raises(hub_manager_access.HubManagerAccessError) as replay:
        hub_manager_access.consume_authorization(
            nonce=str(evidence["evidence_nonce"]),
            action="backup-now",
            hub_id="hub-123",
        )
    assert replay.value.reason_code in {
        "hub_owner_authorization_missing_or_expired",
        "hub_owner_authorization_already_consumed",
    }


@pytest.mark.parametrize(
    "actor",
    [
        _Actor(role="agent", is_owner=False),
        _Actor(is_active=False),
    ],
)
def test_hub_refuses_employee_and_inactive_owner_authorization(
    monkeypatch: pytest.MonkeyPatch,
    actor: _Actor,
) -> None:
    _ensure_django()
    from server.services import hub_manager_access

    monkeypatch.setattr(hub_manager_access, "cache", _MemoryGrantCache())
    with pytest.raises(hub_manager_access.HubManagerAccessError) as exc_info:
        hub_manager_access.issue_authorization(
            actor=actor,
            action="backup-now",
            hub_binding=_binding(),
        )
    expected = (
        "hub_owner_authorization_user_inactive"
        if not actor.is_active
        else "hub_owner_authorization_role_not_allowed"
    )
    assert exc_info.value.reason_code == expected


def test_hub_rechecks_active_role_when_consuming_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_django()
    from server.services import hub_manager_access

    grant_cache = _MemoryGrantCache()
    actor = _Actor()
    monkeypatch.setattr(hub_manager_access, "cache", grant_cache)
    evidence = hub_manager_access.issue_authorization(
        actor=actor,
        action="rename-hub",
        hub_binding=_binding(),
    )
    actor.is_active = False
    user_model = type("UserModel", (), {"objects": _UserManager(actor)})
    monkeypatch.setattr(hub_manager_access, "get_user_model", lambda: user_model)

    with pytest.raises(hub_manager_access.HubManagerAccessError) as exc_info:
        hub_manager_access.consume_authorization(
            nonce=str(evidence["evidence_nonce"]),
            action="rename-hub",
            hub_id="hub-123",
        )
    assert exc_info.value.reason_code == "hub_owner_authorization_user_inactive"


def test_hub_manager_routes_expose_explicit_permissions_and_policies() -> None:
    _ensure_django()
    from core.contracts.route_policy_registry import ROUTE_POLICIES
    from server.api import views_hub_manager

    assert "hub-manager/owner-state/" in ROUTE_POLICIES
    assert "hub-manager/authorizations/" in ROUTE_POLICIES
    assert "hub-manager/authorizations/consume/" in ROUTE_POLICIES
    for view in (
        views_hub_manager.hub_manager_owner_state,
        views_hub_manager.hub_manager_authorization_issue,
        views_hub_manager.hub_manager_authorization_consume,
    ):
        assert getattr(getattr(view, "cls", None), "permission_classes", None)
