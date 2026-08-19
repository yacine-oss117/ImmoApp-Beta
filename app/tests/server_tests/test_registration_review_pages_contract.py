from __future__ import annotations

import os

from rest_framework.test import APIRequestFactory


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _disable_throttles(monkeypatch) -> None:
    from server.api import throttling as throttling_module

    monkeypatch.setattr(
        throttling_module._HeaderThrottleMixin,
        "allow_request",
        lambda self, request, view: True,
    )


def test_registration_approve_get_returns_styled_review_html(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_registration

    _disable_throttles(monkeypatch)
    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "load_registration_for_review",
        lambda *, signed_token: {"id": signed_token},
    )
    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "registration_review_details",
        lambda _record: {
            "agency_name": "Acme",
            "legal_name": "Acme SARL",
            "registry_number": "R123",
            "address": "1 Main St",
            "city": "Algiers",
            "postal_code": "16000",
            "owner_name": "Owner",
            "owner_email": "owner@example.com",
            "owner_phone": "+213600000000",
            "submitted_at": "2026-03-02 10:00",
        },
    )
    request = APIRequestFactory().get("/api/v1/auth/register/approve/token/")
    response = views_registration.auth_register_approve(request, signed_token="token")
    content = response.content.decode("utf-8", errors="ignore")
    assert response.status_code == 200
    assert "<form method='POST'>" in content
    assert "<style>" in content
    assert "width=device-width, initial-scale=1" in content
    assert "cursor:pointer;}}" not in content


def test_registration_approve_post_returns_styled_result_html(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_registration

    _disable_throttles(monkeypatch)
    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "load_registration_for_review",
        lambda *, signed_token: {"id": signed_token},
    )
    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "approve_registration_by_token",
        lambda *, signed_token: {"status": "approved"},
    )
    request = APIRequestFactory().post("/api/v1/auth/register/approve/token/", {})
    response = views_registration.auth_register_approve(request, signed_token="token")
    content = response.content.decode("utf-8", errors="ignore")
    assert response.status_code == 200
    assert "<style>" in content
    assert "Agency approved. The owner&#x27;s email is queued for delivery." in content


def test_registration_blacklist_post_error_returns_styled_html(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_registration

    _disable_throttles(monkeypatch)
    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "load_registration_for_review",
        lambda *, signed_token: {"id": signed_token},
    )

    def _raise_already_processed(*, signed_token: str):
        raise ValueError("Registration request is no longer pending.")

    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "blacklist_registration_by_token",
        _raise_already_processed,
    )
    request = APIRequestFactory().post("/api/v1/auth/register/blacklist/token/", {})
    response = views_registration.auth_register_blacklist(request, signed_token="token")
    content = response.content.decode("utf-8", errors="ignore")
    assert response.status_code == 409
    assert "<style>" in content
    assert "Registration request is no longer pending." in content
