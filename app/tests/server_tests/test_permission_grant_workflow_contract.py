from __future__ import annotations

import os
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from server.services.errors import PermissionDeniedError


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _create_agency():
    from server.accounts.models import Agency

    suffix = uuid.uuid4().hex[:8]
    return Agency.objects.create(
        legal_name=f"Agency {suffix}",
        display_name=f"Agency {suffix}",
        agency_code=f"PRIV{suffix}",
    )


def _unique_email(seed: str) -> str:
    local, _, domain = seed.partition("@")
    resolved_domain = domain or "example.com"
    return f"{local}-{uuid.uuid4().hex[:8]}@{resolved_domain}"


def _create_manager(*, agency, email: str, owner: bool):
    User = get_user_model()
    unique_email = _unique_email(email)
    user = User(
        username=unique_email,
        email=unique_email,
        role="manager",
        agency=agency,
        manager=None,
        is_owner=owner,
        is_active=True,
    )
    user.set_password("StrongPassword!123")
    user.save(validate=False)
    return user


def _create_agent(*, agency, manager, email: str):
    User = get_user_model()
    unique_email = _unique_email(email)
    user = User(
        username=unique_email,
        email=unique_email,
        role="agent",
        agency=agency,
        manager=manager,
        is_owner=False,
        is_active=True,
        can_import=False,
        import_granted_by=None,
    )
    user.set_password("StrongPassword!123")
    user.save(validate=False)
    return user


def test_permission_request_enforces_actor_and_agency_scope() -> None:
    _ensure_django()
    import pytest

    from server.services import permission_elevation

    agency_a = _create_agency()
    agency_b = _create_agency()
    owner_a = _create_manager(agency=agency_a, email="owner-a@example.com", owner=True)
    manager_a = _create_manager(agency=agency_a, email="manager-a@example.com", owner=False)
    agent_a = _create_agent(agency=agency_a, manager=manager_a, email="agent-a@example.com")
    agent_b = _create_agent(
        agency=agency_b,
        manager=_create_manager(agency=agency_b, email="manager-b@example.com", owner=False),
        email="agent-b@example.com",
    )

    created = permission_elevation.request_elevation(
        actor=manager_a,
        user_id=agent_a.id,
        permission="can_import",
        reason="busy day",
    )
    assert created["status"] == "pending"

    with pytest.raises(PermissionDeniedError, match="Forbidden agency scope."):
        permission_elevation.request_elevation(
            actor=owner_a,
            user_id=agent_b.id,
            permission="can_import",
            reason="cross-tenant",
        )


def test_permission_approve_deny_revoke_preserve_boundaries_and_side_effects(monkeypatch) -> None:
    _ensure_django()
    import pytest

    from server.services import permission_elevation

    agency = _create_agency()
    owner = _create_manager(agency=agency, email="owner@example.com", owner=True)
    manager = _create_manager(agency=agency, email="manager@example.com", owner=False)
    agent = _create_agent(agency=agency, manager=manager, email="agent@example.com")

    events: list[dict[str, object]] = []
    alerts: list[dict[str, object]] = []
    monkeypatch.setattr(
        "server.services.auth_events.log_auth_event", lambda **kwargs: events.append(kwargs)
    )
    monkeypatch.setattr(
        "server.services.auth_security_alerts.emit_security_alert",
        lambda **kwargs: alerts.append(kwargs),
    )

    pending = permission_elevation.request_elevation(
        actor=manager,
        user_id=agent.id,
        permission="can_import",
        reason="import rush",
    )

    with pytest.raises(PermissionDeniedError, match="Owner access required."):
        permission_elevation.decide_request(
            actor=manager,
            request_id=int(pending["id"]),
            approve=True,
            duration_minutes=30,
        )

    approved = permission_elevation.decide_request(
        actor=owner,
        request_id=int(pending["id"]),
        approve=True,
        duration_minutes=30,
    )
    assert approved["status"] == "approved"
    assert (
        permission_elevation.has_effective_permission(user=agent, permission="can_import") is True
    )
    assert any(event["event_type"] == "privilege_elevation_approved" for event in events)
    assert any(alert["reason_code"] == "privilege_spike" for alert in alerts)

    revoked = permission_elevation.revoke_request(
        actor=owner,
        request_id=int(pending["id"]),
        reason="done",
    )
    assert revoked["status"] == "revoked"
    assert (
        permission_elevation.has_effective_permission(user=agent, permission="can_import") is False
    )
    assert any(event["event_type"] == "privilege_elevation_revoked" for event in events)

    pending_deny = permission_elevation.request_elevation(
        actor=manager,
        user_id=agent.id,
        permission="can_hard_delete",
        reason="cleanup",
    )
    denied = permission_elevation.decide_request(
        actor=owner,
        request_id=int(pending_deny["id"]),
        approve=False,
        reason="not allowed",
    )
    assert denied["status"] == "denied"
    assert denied["revoke_reason"] == "not allowed"
    assert any(event["event_type"] == "privilege_elevation_denied" for event in events)
    assert len(alerts) == 1


def test_permission_effective_permissions_expiry_semantics_hold() -> None:
    _ensure_django()
    from server.accounts.models import PrivilegeElevationRequest
    from server.services import permission_elevation

    agency = _create_agency()
    owner = _create_manager(agency=agency, email="owner-exp@example.com", owner=True)
    agent = _create_agent(agency=agency, manager=owner, email="agent-exp@example.com")

    PrivilegeElevationRequest.objects.create(
        agency=agency,
        user=agent,
        permission=PrivilegeElevationRequest.PERMISSION_CAN_IMPORT,
        status=PrivilegeElevationRequest.STATUS_APPROVED,
        requested_by=owner,
        approved_by=owner,
        decided_at=timezone.now(),
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    effective = permission_elevation.list_effective_permissions(user=agent)
    assert effective["can_import"] is False
    assert effective["can_hard_delete"] is False
