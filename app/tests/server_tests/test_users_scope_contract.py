from __future__ import annotations

import os
from dataclasses import dataclass

from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _User:
    id: int = 7
    pk: int = 7
    username: str = "scope-user"
    role: str = "manager"
    is_superuser: bool = False
    agency_id: int = 12
    is_authenticated: bool = True


def test_users_scope_all_throttle_rate_is_configured() -> None:
    _ensure_django()
    from server.immoapp_server import settings_api

    rates = settings_api.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {})
    assert isinstance(rates, dict)
    assert "users_scope_all" in rates
    assert str(rates["users_scope_all"]).strip()


def test_users_list_rejects_invalid_scope() -> None:
    _ensure_django()
    from server.api import views_users

    factory = APIRequestFactory()
    request = factory.get("/api/v1/users/?scope=invalid")
    force_authenticate(request, user=_User())
    response = views_users.users_list(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_users_list_scope_all_requires_superuser(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_users

    factory = APIRequestFactory()
    request = factory.get("/api/v1/users/?scope=all")
    force_authenticate(request, user=_User(is_superuser=False))

    monkeypatch.setattr(views_users, "require_manager", lambda _request: None)
    monkeypatch.setattr(
        views_users,
        "require_superuser",
        lambda _request: Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN),
    )

    audited: list[tuple[str, str | None]] = []

    def _audit(request, *, outcome: str, reason_code: str | None = None, **kwargs):
        _ = request, kwargs
        audited.append((outcome, reason_code))

    monkeypatch.setattr(views_users, "_audit_scope_all_access", _audit)

    response = views_users.users_list(request)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert audited == [("denied", "not_superuser")]


def test_users_list_scope_all_passes_explicit_scope_and_audits(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_users

    factory = APIRequestFactory()
    request = factory.get("/api/v1/users/?scope=all&include_inactive=1&role=manager&agency_id=33")
    force_authenticate(request, user=_User(is_superuser=True, role="super_admin"))

    monkeypatch.setattr(views_users, "require_manager", lambda _request: None)
    monkeypatch.setattr(views_users, "require_superuser", lambda _request: None)
    monkeypatch.setattr(views_users, "_scope_all_throttle_response", lambda _request: None)

    captured: dict[str, object] = {}

    def _list_users_page(*, actor, include_inactive, role, agency_id, scope, q, limit, cursor):
        captured.update(
            {
                "actor": actor,
                "include_inactive": include_inactive,
                "role": role,
                "agency_id": agency_id,
                "scope": scope,
                "q": q,
                "limit": limit,
                "cursor": cursor,
            }
        )
        return [], None, False

    monkeypatch.setattr(views_users.users, "list_users_page", _list_users_page)

    audited: list[str] = []

    def _audit(request, *, outcome: str, **kwargs):
        _ = request, kwargs
        audited.append(outcome)

    monkeypatch.setattr(views_users, "_audit_scope_all_access", _audit)

    response = views_users.users_list(request)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["next_cursor"] is None
    assert response.data["has_more"] is False
    assert response.data["total_returned"] == 0
    assert captured["scope"] == "all"
    assert captured["agency_id"] == 33
    assert captured["include_inactive"] is True
    assert captured["role"] == "manager"
    assert captured["q"] is None
    assert captured["limit"] == 50
    assert captured["cursor"] is None
    assert audited == ["success"]
