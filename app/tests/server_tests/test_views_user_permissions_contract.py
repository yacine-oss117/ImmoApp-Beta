from __future__ import annotations

import os

from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


class _User:
    def __init__(self, *, user_id: int = 11, role: str = "manager", owner: bool = True) -> None:
        self.id = user_id
        self.role = role
        self.is_owner = owner
        self.is_superuser = False
        self.is_authenticated = True
        self.agency_id = 1


def test_user_permission_grants_get_returns_items(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_user_permissions

    monkeypatch.setattr(
        views_user_permissions.permission_elevation,
        "list_requests",
        lambda **_: [{"id": 1, "status": "pending"}],
    )
    request = APIRequestFactory().get("/api/v1/users/permissions/grants/")
    force_authenticate(request, user=_User(owner=False))
    response = views_user_permissions.user_permission_grants(request)
    assert response.status_code == 200
    assert response.data["total"] == 1


def test_user_permission_grants_post_creates_request(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_user_permissions

    monkeypatch.setattr(views_user_permissions, "require_step_up", lambda _req: None)
    monkeypatch.setattr(
        views_user_permissions.permission_elevation,
        "request_elevation",
        lambda **_: {"id": 33, "status": "pending"},
    )
    request = APIRequestFactory().post(
        "/api/v1/users/permissions/grants/",
        {"user_id": 22, "permission": "can_import", "reason": "import rush"},
        format="json",
    )
    force_authenticate(request, user=_User())
    response = views_user_permissions.user_permission_grants(request)
    assert response.status_code == 201
    assert response.data["id"] == 33


def test_user_permission_grant_approve_calls_service(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_user_permissions

    monkeypatch.setattr(views_user_permissions, "require_step_up", lambda _req: None)
    monkeypatch.setattr(
        views_user_permissions.permission_elevation,
        "decide_request",
        lambda **_: {"id": 44, "status": "approved"},
    )
    request = APIRequestFactory().post(
        "/api/v1/users/permissions/grants/44/approve/",
        {"duration_minutes": 30},
        format="json",
    )
    force_authenticate(request, user=_User(owner=True))
    response = views_user_permissions.user_permission_grant_approve(request, request_id=44)
    assert response.status_code == 200
    assert response.data["status"] == "approved"
