from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    pytest.importorskip(
        "daphne",
        reason="match count endpoint contract tests require server deps",
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _User:
    id: int = 17
    pk: int = 17
    username: str = "agent"
    role: str = "agent"
    is_owner: bool = False
    is_superuser: bool = False
    agency_id: int = 42
    is_authenticated: bool = True


def test_matches_count_clients_requires_ids(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    factory = APIRequestFactory()
    request = factory.get("/api/v1/matches/clients/counts/")
    force_authenticate(request, user=_User())

    def _no_all() -> dict[int, int]:
        raise AssertionError("count_matches_for_all_clients must not be called")

    monkeypatch.setattr(views_matches.matches, "count_matches_for_all_clients", _no_all)

    response = views_matches.matches_count_clients(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "MISSING_IDS"
    assert response.data["async_endpoint"] == "/api/v1/matches/clients/all/"


def test_matches_count_demandes_requires_ids(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    factory = APIRequestFactory()
    request = factory.post("/api/v1/matches/demandes/counts/", {}, format="json")
    force_authenticate(request, user=_User())

    def _no_all() -> dict[int, int]:
        raise AssertionError("count_matches_for_all_demandes must not be called")

    monkeypatch.setattr(views_matches.matches, "count_matches_for_all_demandes", _no_all)

    response = views_matches.matches_count_demandes(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "MISSING_IDS"
    assert response.data["async_endpoint"] == "/api/v1/matches/demandes/all/"


def test_matches_count_clients_with_ids_returns_counts(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    captured: dict[str, object] = {}

    def _count(ids: list[int]) -> dict[int, int]:
        captured["ids"] = ids
        return {ids[0]: 3}

    monkeypatch.setattr(views_matches.matches, "count_matches_for_clients", _count)
    factory = APIRequestFactory()
    request = factory.get("/api/v1/matches/clients/counts/?id=9")
    force_authenticate(request, user=_User())

    response = views_matches.matches_count_clients(request)
    assert response.status_code == status.HTTP_200_OK
    assert captured["ids"] == [9]
    assert response.data["counts"] == {9: 3}


def test_matches_count_clients_rejects_invalid_ids() -> None:
    _ensure_django()
    from server.api import views_matches

    factory = APIRequestFactory()
    request = factory.get("/api/v1/matches/clients/counts/?id=9&id=abc")
    force_authenticate(request, user=_User())

    response = views_matches.matches_count_clients(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "INVALID_IDS"


def test_matches_count_clients_rejects_non_positive_ids() -> None:
    _ensure_django()
    from server.api import views_matches

    factory = APIRequestFactory()
    request = factory.get("/api/v1/matches/clients/counts/?id=0")
    force_authenticate(request, user=_User())

    response = views_matches.matches_count_clients(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "INVALID_IDS"


def test_matches_count_listings_requires_ids(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    factory = APIRequestFactory()
    request = factory.get("/api/v1/matches/listings/counts/")
    force_authenticate(request, user=_User())

    def _no_all() -> dict[int, int]:
        raise AssertionError("count_matches_for_all_listings must not be called")

    monkeypatch.setattr(views_matches.matches, "count_matches_for_all_listings", _no_all)

    response = views_matches.matches_count_listings(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "MISSING_IDS"
    assert response.data["async_endpoint"] == "/api/v1/matches/listings/all/"


def test_matches_count_offers_requires_ids(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    factory = APIRequestFactory()
    request = factory.post("/api/v1/matches/offers/counts/", {}, format="json")
    force_authenticate(request, user=_User())

    def _no_all() -> dict[int, int]:
        raise AssertionError("count_matches_for_all_offers must not be called")

    monkeypatch.setattr(views_matches.matches, "count_matches_for_all_offers", _no_all)

    response = views_matches.matches_count_offers(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "MISSING_IDS"
    assert response.data["async_endpoint"] == "/api/v1/matches/offers/all/"
