from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    pytest.importorskip("daphne", reason="diagnostics enrollment token tests require server deps")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _User:
    id: int = 12
    pk: int = 12
    username: str = "diag-token-user"
    role: str = "agent"
    is_owner: bool = False
    is_superuser: bool = False
    agency_id: int = 42
    is_authenticated: bool = True


def test_diagnostics_enrollment_token_can_only_be_used_once(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_diagnostics_keys
    from server.api.step_up import issue_step_up_token
    from server.services.errors import PermissionDeniedError

    used_tokens: set[str] = set()
    issued_token = "diag-enroll-token-1"

    def _register_signing_key(**kwargs):
        token = str(kwargs.get("enrollment_token") or "")
        if not token:
            raise PermissionDeniedError("Enrollment token is required.")
        if token in used_tokens:
            raise PermissionDeniedError("Enrollment token already used.")
        used_tokens.add(token)
        return {
            "id": 101,
            "agency_id": 42,
            "device_id": kwargs["device_id"],
            "signature_key_id": kwargs["signature_key_id"],
            "is_active": True,
            "created": True,
        }

    monkeypatch.setattr(
        views_diagnostics_keys.diagnostics_keys,
        "register_signing_key",
        _register_signing_key,
    )

    factory = APIRequestFactory()
    payload = {
        "device_id": "device-2",
        "signature_key_id": "sig-2",
        "public_key": "PUBKEY-2",
        "enrollment_token": issued_token,
    }

    first = factory.post("/api/v1/diagnostics/keys/register/", payload, format="json")
    force_authenticate(first, user=_User())
    first.META["HTTP_X_IMMOAPP_STEP_UP"] = issue_step_up_token(user_id=12)
    first_response = views_diagnostics_keys.diagnostics_key_register(first)
    assert first_response.status_code == status.HTTP_201_CREATED

    second = factory.post("/api/v1/diagnostics/keys/register/", payload, format="json")
    force_authenticate(second, user=_User())
    second.META["HTTP_X_IMMOAPP_STEP_UP"] = issue_step_up_token(user_id=12)
    second_response = views_diagnostics_keys.diagnostics_key_register(second)
    assert second_response.status_code == status.HTTP_403_FORBIDDEN
