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
    id: int = 21
    pk: int = 21
    username: str = "manager-user"
    role: str = "manager"
    is_owner: bool = True
    is_superuser: bool = False
    agency_id: int = 12
    is_authenticated: bool = True


def test_notifications_list_rejects_query_budget_excess() -> None:
    _ensure_django()
    from server.api import views_notifications

    request = APIRequestFactory().get("/api/v1/notifications/?limit=500&offset=800")
    force_authenticate(request, user=_User())
    response = views_notifications.notifications_list(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "QUERY_BUDGET_EXCEEDED"


def test_notifications_list_allows_budget_and_calls_service(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_notifications

    called = {"list_with_total": False}

    class _NoCache:
        def get_or_fill(self, *, fill_fn, **_kwargs):
            return fill_fn()

    def _list_notification_items_with_total(**kwargs):
        called["list_with_total"] = True
        assert kwargs["limit"] == 200
        assert kwargs["offset"] == 50
        return [], 0

    monkeypatch.setattr(
        views_notifications.notifications,
        "list_notification_items_with_total",
        _list_notification_items_with_total,
    )
    monkeypatch.setattr(views_notifications, "get_response_cache", lambda: _NoCache())

    request = APIRequestFactory().get("/api/v1/notifications/?limit=200&offset=50")
    force_authenticate(request, user=_User())
    response = views_notifications.notifications_list(request)
    assert response.status_code == status.HTTP_200_OK
    assert called["list_with_total"] is True


def test_clients_list_rejects_query_budget_excess() -> None:
    _ensure_django()
    from server.api import views_clients_list

    request = APIRequestFactory().get("/api/v1/clients/?limit=500&offset=901")
    force_authenticate(request, user=_User())
    response = views_clients_list.clients_list(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "QUERY_BUDGET_EXCEEDED"


def test_listings_list_rejects_query_budget_excess() -> None:
    _ensure_django()
    from server.api import views_listings_list

    request = APIRequestFactory().get("/api/v1/listings/?limit=500&offset=901")
    force_authenticate(request, user=_User())
    response = views_listings_list.listings_list(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "QUERY_BUDGET_EXCEEDED"
