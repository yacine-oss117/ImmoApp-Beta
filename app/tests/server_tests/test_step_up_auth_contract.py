from __future__ import annotations

import os
from dataclasses import dataclass

from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _User:
    id: int = 77
    pk: int = 77
    username: str = "manager77"
    agency_id: int = 12
    is_authenticated: bool = True

    def check_password(self, raw: str) -> bool:
        return raw == "correct-password"


def test_step_up_auth_scope_is_configured() -> None:
    _ensure_django()
    from server.immoapp_server import settings_api

    rates = settings_api.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {})
    assert isinstance(rates, dict)
    assert "step_up_auth" in rates
    assert str(rates["step_up_auth"]).strip()


def test_step_up_auth_view_issues_token_for_valid_password(monkeypatch) -> None:
    _ensure_django()
    from server.api.auth_account_views import StepUpAuthView

    monkeypatch.setattr(
        "server.api.auth_account_views.auth_events.log_auth_event", lambda **_: None
    )
    request = APIRequestFactory().post(
        "/api/auth/step-up/",
        {"password": "correct-password"},
        format="json",
    )
    force_authenticate(request, user=_User())
    response = StepUpAuthView.as_view()(request)
    assert response.status_code == status.HTTP_200_OK
    assert isinstance(response.data.get("step_up_token"), str)
    assert int(response.data.get("expires_in_seconds", 0)) > 0


def test_step_up_auth_view_rejects_invalid_password(monkeypatch) -> None:
    _ensure_django()
    from server.api.auth_account_views import StepUpAuthView

    monkeypatch.setattr(
        "server.api.auth_account_views.auth_events.log_auth_event", lambda **_: None
    )
    request = APIRequestFactory().post(
        "/api/auth/step-up/",
        {"password": "wrong-password"},
        format="json",
    )
    force_authenticate(request, user=_User())
    response = StepUpAuthView.as_view()(request)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_require_step_up_accepts_valid_token(monkeypatch) -> None:
    _ensure_django()
    from server.api.step_up import issue_step_up_token, require_step_up

    monkeypatch.setenv("IMMOAPP_REQUIRE_STEP_UP_SENSITIVE", "1")
    token = issue_step_up_token(user_id=77)
    request = APIRequestFactory().post("/api/v1/users/", {}, format="json")
    request.META["HTTP_X_IMMOAPP_STEP_UP"] = token
    request.user = _User()
    assert require_step_up(request) is None


def test_require_step_up_rejects_missing_token(monkeypatch) -> None:
    _ensure_django()
    from server.api.step_up import require_step_up

    monkeypatch.setenv("IMMOAPP_REQUIRE_STEP_UP_SENSITIVE", "1")
    request = APIRequestFactory().post("/api/v1/users/", {}, format="json")
    request.user = _User()
    response = require_step_up(request)
    assert response is not None
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["code"] == "STEP_UP_REQUIRED"
