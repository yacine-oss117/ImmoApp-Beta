from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    pytest.importorskip("daphne", reason="diagnostics enrollment authz tests require server deps")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _User:
    id: int = 11
    pk: int = 11
    username: str = "diag-user"
    role: str = "manager"
    is_owner: bool = False
    is_superuser: bool = False
    agency_id: int = 42
    is_authenticated: bool = True


def test_diagnostics_key_register_rejects_unauthenticated() -> None:
    _ensure_django()
    from server.api import views_diagnostics_keys

    factory = APIRequestFactory()
    request = factory.post(
        "/api/v1/diagnostics/keys/register/",
        {
            "device_id": "device-1",
            "signature_key_id": "sig-1",
            "public_key": "PUBKEY",
        },
        format="json",
    )
    response = views_diagnostics_keys.diagnostics_key_register(request)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_diagnostics_key_register_rejects_non_admin_without_token(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_diagnostics_keys
    from server.api.step_up import issue_step_up_token
    from server.services.errors import PermissionDeniedError

    factory = APIRequestFactory()
    request = factory.post(
        "/api/v1/diagnostics/keys/register/",
        {
            "device_id": "device-1",
            "signature_key_id": "sig-1",
            "public_key": "PUBKEY",
        },
        format="json",
    )
    force_authenticate(request, user=_User(is_owner=False))
    request.META["HTTP_X_IMMOAPP_STEP_UP"] = issue_step_up_token(user_id=11)

    def _deny_register(**kwargs):
        _ = kwargs
        raise PermissionDeniedError("Tenant admin approval required.")

    monkeypatch.setattr(
        views_diagnostics_keys.diagnostics_keys,
        "register_signing_key",
        _deny_register,
    )
    response = views_diagnostics_keys.diagnostics_key_register(request)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_diagnostics_key_register_allows_admin_approved_flow(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_diagnostics_keys
    from server.api.step_up import issue_step_up_token

    factory = APIRequestFactory()
    request = factory.post(
        "/api/v1/diagnostics/keys/register/",
        {
            "device_id": "device-1",
            "signature_key_id": "sig-1",
            "public_key": "PUBKEY",
            "admin_approved": True,
        },
        format="json",
    )
    force_authenticate(request, user=_User(is_owner=True))
    request.META["HTTP_X_IMMOAPP_STEP_UP"] = issue_step_up_token(user_id=11)

    captured: dict[str, object] = {}

    def _allow_register(**kwargs):
        captured.update(kwargs)
        return {
            "id": 1,
            "agency_id": 42,
            "device_id": "device-1",
            "signature_key_id": "sig-1",
            "is_active": True,
            "created": True,
        }

    monkeypatch.setattr(
        views_diagnostics_keys.diagnostics_keys,
        "register_signing_key",
        _allow_register,
    )
    response = views_diagnostics_keys.diagnostics_key_register(request)
    assert response.status_code == status.HTTP_201_CREATED
    assert captured.get("admin_approved") is True
