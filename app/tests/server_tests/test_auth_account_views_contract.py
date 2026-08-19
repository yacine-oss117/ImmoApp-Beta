from __future__ import annotations

import os

from rest_framework import status
from rest_framework.test import APIRequestFactory


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def test_password_forgot_view_calls_service_and_returns_200(monkeypatch) -> None:
    _ensure_django()
    from server.api.auth_account_views import PasswordForgotView
    from server.services import user_auth_lifecycle

    captured: dict[str, object] = {}

    def _request_password_reset(**kwargs):
        captured.update(kwargs)
        return {"status": "accepted"}

    monkeypatch.setattr(user_auth_lifecycle, "request_password_reset", _request_password_reset)
    request = APIRequestFactory().post(
        "/api/auth/password/forgot/",
        {"identifier": "user@example.com"},
        format="json",
    )
    response = PasswordForgotView.as_view()(request)
    assert response.status_code == status.HTTP_200_OK
    assert captured["identifier"] == "user@example.com"


def test_password_reset_view_maps_permission_denied_to_403(monkeypatch) -> None:
    _ensure_django()
    from server.api.auth_account_views import PasswordResetView
    from server.services import user_auth_lifecycle
    from server.services.errors import PermissionDeniedError

    def _reset_password_with_token(**kwargs):
        _ = kwargs
        raise PermissionDeniedError("Invalid or expired token.")

    monkeypatch.setattr(
        user_auth_lifecycle, "reset_password_with_token", _reset_password_with_token
    )
    request = APIRequestFactory().post(
        "/api/auth/password/reset/",
        {"token": "bad", "new_password": "Password_123"},
        format="json",
    )
    response = PasswordResetView.as_view()(request)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_account_activate_view_returns_410_legacy_retired(monkeypatch) -> None:
    _ensure_django()
    from server.api.auth_account_views import AccountActivateView

    _ = monkeypatch
    request = APIRequestFactory().post(
        "/api/auth/account/activate/",
        {"token": "ok-token", "password": "Password_123"},
        format="json",
    )
    response = AccountActivateView.as_view()(request)
    assert response.status_code == status.HTTP_410_GONE
    assert response.data.get("code") == "LEGACY_ACTIVATION_RETIRED"
