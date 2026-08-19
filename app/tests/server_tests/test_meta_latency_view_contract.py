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
    id: int = 1
    pk: int = 1
    username: str = "root"
    role: str = "super_admin"
    is_superuser: bool = True
    agency_id: int = 1
    is_authenticated: bool = True


def test_meta_latency_requires_superuser() -> None:
    _ensure_django()
    from server.api import views_meta_latency

    request = APIRequestFactory().get("/api/v1/meta/latency/")
    force_authenticate(request, user=_User(is_superuser=False))
    response = views_meta_latency.meta_latency(request)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_meta_latency_returns_snapshots(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_meta_latency

    monkeypatch.setattr(
        views_meta_latency,
        "list_latency_snapshots",
        lambda *, limit=50: [
            {
                "route_name": "route.users",
                "sample_count": 12,
                "p50_ms": 20.0,
                "p95_ms": 50.0,
                "p99_ms": 70.0,
                "window_seconds": 600,
            }
        ],
    )
    request = APIRequestFactory().get("/api/v1/meta/latency/?limit=20")
    force_authenticate(request, user=_User())
    response = views_meta_latency.meta_latency(request)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["total"] == 1
    assert response.data["items"][0]["route_name"] == "route.users"
