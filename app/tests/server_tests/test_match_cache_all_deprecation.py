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
    id: int = 11
    is_authenticated: bool = True
    is_superuser: bool = False
    agency_id: int = 42


def test_match_cache_all_returns_deprecation_headers(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_cache_tasks

    factory = APIRequestFactory()
    request = factory.get("/api/v1/cache/match/all/")
    force_authenticate(request, user=_User())

    calls: list[tuple[str, str]] = []

    def _record(*, cache_name: str, outcome: str, count: int = 1) -> None:
        _ = count
        calls.append((cache_name, outcome))

    monkeypatch.setattr(views_cache_tasks, "record_match_cache_lookup", _record)

    response = views_cache_tasks.match_cache_all(request)
    assert response.status_code == status.HTTP_410_GONE
    assert response.data["error"] == "ENDPOINT_RETIRED"
    assert "/api/v1/cache/match/get" in response.data["replacement"]
    assert response.get("Deprecation") == "true"
    assert "deprecated" in str(response.get("Warning", "")).lower()
    assert calls == [("match_counts_cache_all_endpoint", "retired_call")]


def test_match_cache_all_has_dedicated_throttle_scope() -> None:
    _ensure_django()
    from server.api import views_cache_tasks

    assert getattr(views_cache_tasks.match_cache_all, "throttle_scope", None) == "match_cache_all"
