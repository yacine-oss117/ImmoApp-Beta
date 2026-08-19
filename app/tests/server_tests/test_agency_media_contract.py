from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def _setup_django() -> None:
    repo_root = Path(__file__).parents[3]
    server_dir = repo_root / "server"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django

    django.setup()


class _User:
    def __init__(self) -> None:
        self.id = 1
        self.role = "manager"
        self.pk = self.id

    @property
    def is_authenticated(self) -> bool:  # pragma: no cover - required by DRF
        return True


def test_agency_media_default_returns_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_django()
    from rest_framework.test import APIRequestFactory, force_authenticate

    from server.api.views_agency import agency_media

    payload = {
        "url": "https://example.test/logo.png",
        "filename": "logo.png",
        "expires_in": 90,
    }

    monkeypatch.setattr(
        "server.api.views_agency.media.get_agency_media_url",
        lambda *_a, **_k: payload,
    )

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("load_agency_media should not be called for default URL mode")

    monkeypatch.setattr("server.api.views_agency.media.load_agency_media", _unexpected)

    factory = APIRequestFactory()
    request = factory.get("/api/v1/settings/agency/media", {"kind": "logo"})
    force_authenticate(request, user=_User())
    response = agency_media(request)
    assert response.status_code == 200
    assert response.data == payload


def test_agency_media_inline_returns_b64(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_django()
    from rest_framework.test import APIRequestFactory, force_authenticate

    from server.api.views_agency import agency_media

    monkeypatch.setattr(
        "server.api.views_agency.media.load_agency_media",
        lambda *_a, **_k: ("logo.png", b"abc"),
    )

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("get_agency_media_url should not be called for inline mode")

    monkeypatch.setattr("server.api.views_agency.media.get_agency_media_url", _unexpected)

    factory = APIRequestFactory()
    request = factory.get(
        "/api/v1/settings/agency/media",
        {"kind": "logo", "mode": "inline"},
    )
    force_authenticate(request, user=_User())
    response = agency_media(request)
    assert response.status_code == 200
    assert response.data.get("filename") == "logo.png"
    assert response.data.get("content_b64") == "YWJj"


def test_agency_media_inline_fallbacks_to_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_django()
    from rest_framework.test import APIRequestFactory, force_authenticate

    from server.api.views_agency import agency_media

    monkeypatch.setattr(
        "server.api.views_agency.media.load_agency_media",
        lambda *_a, **_k: None,
    )
    payload = {
        "url": "https://example.test/logo.png",
        "filename": "logo.png",
        "expires_in": 90,
    }
    monkeypatch.setattr(
        "server.api.views_agency.media.get_agency_media_url",
        lambda *_a, **_k: payload,
    )

    factory = APIRequestFactory()
    request = factory.get(
        "/api/v1/settings/agency/media",
        {"kind": "logo", "mode": "inline"},
    )
    force_authenticate(request, user=_User())
    response = agency_media(request)
    assert response.status_code == 200
    assert response.data.get("url") == payload["url"]
    assert response.data.get("inline") is False
