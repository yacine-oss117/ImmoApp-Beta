from __future__ import annotations

import os
import uuid

from django.contrib.auth import get_user_model


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
        agency_code=f"AUTH{suffix}",
        max_users=5,
        max_managers=3,
    )


def _unique_email(seed: str) -> str:
    local, _, domain = seed.partition("@")
    resolved_domain = domain or "example.com"
    return f"{local}-{uuid.uuid4().hex[:8]}@{resolved_domain}"


def _create_manager(*, agency, email: str, owner: bool, active: bool = True):
    User = get_user_model()
    unique_email = _unique_email(email)
    user = User(
        username=unique_email,
        email=unique_email,
        role="manager",
        agency=agency,
        manager=None,
        is_owner=owner,
        is_active=active,
    )
    user.set_password("StrongPassword!123")
    user.save(validate=False)
    return user


def test_password_reset_request_stays_non_disclosing_for_missing_user(monkeypatch) -> None:
    _ensure_django()
    from server.services import user_auth_lifecycle as module

    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        module.auth_events, "log_auth_event", lambda **kwargs: events.append(kwargs)
    )

    payload = module.request_password_reset(
        identifier="missing@example.com",
        request_id="rid-missing",
        source_ip="10.0.0.1",
        user_agent="ua",
    )

    assert payload == {
        "status": "accepted",
        "message": "If the account exists, reset instructions have been generated.",
    }
    assert events[-1]["event_type"] == "password_reset_request"
    assert events[-1]["outcome"] == "accepted"
    assert events[-1]["reason_code"] == "non_disclosing_accepted"


def test_password_reset_invalid_token_preserves_denial_and_event(monkeypatch) -> None:
    _ensure_django()
    from server.services import user_auth_lifecycle as module

    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        module.auth_events, "log_auth_event", lambda **kwargs: events.append(kwargs)
    )

    import pytest

    with pytest.raises(module.PermissionDeniedError, match="Invalid or expired token."):
        module.reset_password_with_token(
            token="bad-token",
            new_password="AnotherStrongPass_123!",
            request_id="rid-bad",
            source_ip="10.0.0.2",
            user_agent="ua",
        )

    assert events[-1]["event_type"] == "password_reset_complete"
    assert events[-1]["outcome"] == "failure"
    assert events[-1]["reason_code"] == "invalid_token"


def test_user_action_tokens_keep_purpose_isolation_and_one_time_use(monkeypatch) -> None:
    _ensure_django()
    from server.services import user_auth_lifecycle as module

    agency = _create_agency()
    owner = _create_manager(agency=agency, email="owner@example.com", owner=True)

    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        module.auth_events, "log_auth_event", lambda **kwargs: events.append(kwargs)
    )
    monkeypatch.setattr(module, "_DEV_TOKEN_ECHO", True)

    reset_payload = module.request_password_reset(
        identifier=owner.email,
        request_id="rid-reset",
        source_ip="10.0.0.3",
        user_agent="ua",
    )
    reset_token = str(reset_payload["reset_token"])

    import pytest

    with pytest.raises(module.PermissionDeniedError, match="Invalid or expired token."):
        module.activate_account_with_token(
            token=reset_token,
            password="StrongPassword!456",
            request_id="rid-reset-misuse",
            source_ip="10.0.0.4",
            user_agent="ua",
        )

    invite_identity = _unique_email("invitee@example.com")
    invite_payload = module.create_user_invite(
        actor=owner,
        data={
            "username": invite_identity,
            "email": invite_identity,
            "first_name": "Invited",
            "last_name": "User",
            "role": "manager",
        },
    )
    activation_token = str(invite_payload["activation_token"])

    with pytest.raises(module.PermissionDeniedError, match="Invalid or expired token."):
        module.reset_password_with_token(
            token=activation_token,
            new_password="StrongPassword!456",
            request_id="rid-invite-misuse",
            source_ip="10.0.0.5",
            user_agent="ua",
        )

    activated = module.activate_account_with_token(
        token=activation_token,
        password="StrongPassword!789",
        request_id="rid-activate",
        source_ip="10.0.0.6",
        user_agent="ua",
    )
    assert activated["status"] == "account_activated"

    with pytest.raises(module.PermissionDeniedError, match="Invalid or expired token."):
        module.activate_account_with_token(
            token=activation_token,
            password="StrongPassword!789",
            request_id="rid-activate-again",
            source_ip="10.0.0.7",
            user_agent="ua",
        )

    reason_codes = {(event["event_type"], event.get("reason_code")) for event in events}
    assert ("password_reset_complete", "invalid_token") in reason_codes
    assert ("account_activation", "account_activated") in reason_codes
    assert ("account_activation", "token_consumed") in reason_codes
