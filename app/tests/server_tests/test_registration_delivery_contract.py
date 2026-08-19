from __future__ import annotations

import os

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APIRequestFactory


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def test_auth_register_returns_delivery_queued_contract(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_registration

    monkeypatch.setattr(
        views_registration,
        "validate_payload",
        lambda payload, serializer, partial=False: ({"owner_email": "owner@example.com"}, None),
    )
    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "submit_registration",
        lambda **kwargs: {
            "status": "pending",
            "message": "ok",
            "delivery_status": "queued",
            "delivery_detail": "Email queued for delivery.",
        },
    )

    request = APIRequestFactory().post("/api/v1/auth/register/", {}, format="json")
    response = views_registration.auth_register(request)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["delivery_status"] == "queued"
    assert response.data["delivery_detail"] == "Email queued for delivery."


def test_auth_register_returns_503_when_email_queue_unavailable(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_registration

    monkeypatch.setattr(
        views_registration,
        "validate_payload",
        lambda payload, serializer, partial=False: ({"owner_email": "owner@example.com"}, None),
    )

    def _raise_queue(**kwargs):
        _ = kwargs
        raise views_registration.registration_lifecycle.EmailQueueUnavailableError(
            "queue unavailable"
        )

    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "submit_registration",
        _raise_queue,
    )

    request = APIRequestFactory().post("/api/v1/auth/register/", {}, format="json")
    response = views_registration.auth_register(request)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["code"] == "EMAIL_QUEUE_UNAVAILABLE"


def test_auth_activate_maps_password_validation_to_400(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_registration

    monkeypatch.setattr(
        views_registration,
        "validate_payload",
        lambda payload, serializer, partial=False: (
            {
                "email": "owner@example.com",
                "activation_code": "ABCD1234",
                "password": "password",
            },
            None,
        ),
    )

    def _raise_validation(**kwargs):
        _ = kwargs
        raise ValidationError(["The password is too similar to the username."])

    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "activate_owner",
        _raise_validation,
    )

    request = APIRequestFactory().post("/api/v1/auth/activate/", {}, format="json")
    response = views_registration.auth_activate(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["detail"] == "Invalid request"
    assert response.data["errors"]["non_field_errors"] == [
        "The password is too similar to the username."
    ]


def test_auth_accept_invite_maps_password_validation_to_400(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_registration

    monkeypatch.setattr(
        views_registration,
        "validate_payload",
        lambda payload, serializer, partial=False: (
            {
                "invite_code": "ABC123",
                "email": "agent@example.com",
                "password": "password",
            },
            None,
        ),
    )

    def _raise_validation(**kwargs):
        _ = kwargs
        raise ValidationError(["The password is too similar to the username."])

    monkeypatch.setattr(
        views_registration.registration_lifecycle,
        "accept_invite",
        _raise_validation,
    )

    request = APIRequestFactory().post("/api/v1/auth/accept-invite/", {}, format="json")
    response = views_registration.auth_accept_invite(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["detail"] == "Invalid request"
    assert response.data["errors"]["non_field_errors"] == [
        "The password is too similar to the username."
    ]
