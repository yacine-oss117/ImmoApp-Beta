from __future__ import annotations

import os
from datetime import datetime, timezone

from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _user() -> object:
    class _U:
        id = 7
        pk = 7
        agency_id = 3
        username = "manager"
        is_authenticated = True

    return _U()


def test_token_obtain_rejects_when_lockout_active(monkeypatch) -> None:
    _ensure_django()
    from server.api import auth_views
    from server.api.auth_views import SecureTokenObtainPairView

    request = APIRequestFactory().post(
        "/api/auth/token/",
        {"username": "agent", "password": "x"},
        format="json",
    )
    force_authenticate(request, user=_user())
    monkeypatch.setattr(
        "server.services.auth_lockout.locked_until",
        lambda **_: datetime.now(tz=timezone.utc),
    )
    monkeypatch.setattr(auth_views, "_resolve_user_identity", lambda _identifier: (7, 3))
    view = SecureTokenObtainPairView.as_view()
    response = view(request)
    assert response.status_code == 401
    detail = str(response.data.get("detail") or "")
    assert "Too many failed attempts" in detail
