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
    is_superuser: bool = False
    agency_id: int = 12
    is_authenticated: bool = True


def test_users_invites_get_returns_cursor_contract(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_user_invites

    captured: dict[str, object] = {}

    class _PassThroughCache:
        def get_or_fill(self, **kwargs):
            captured["cache_kwargs"] = dict(kwargs)
            return kwargs["fill_fn"]()

    def _list_pending_invites_page(*, actor, limit, cursor):
        captured["actor"] = actor
        captured["limit"] = limit
        captured["cursor"] = cursor
        return [{"invite_id": "abc", "invite_email": "x@example.com"}], None, False

    monkeypatch.setattr(
        views_user_invites.registration_lifecycle,
        "list_pending_invites_page",
        _list_pending_invites_page,
    )
    monkeypatch.setattr(
        views_user_invites.registration_lifecycle,
        "get_pending_invites_surface_generation",
        lambda *, actor: ("invites_actor_surface", 7),
    )
    monkeypatch.setattr(views_user_invites, "get_response_cache", lambda: _PassThroughCache())
    request = APIRequestFactory().get("/api/v1/users/invites/")
    force_authenticate(request, user=_User())
    response = views_user_invites.users_invites(request)
    assert response.status_code == status.HTTP_200_OK
    payload = response.data
    assert payload["total_returned"] == 1
    assert payload["next_cursor"] is None
    assert payload["has_more"] is False
    assert captured["limit"] == 50
    assert captured["cursor"] is None
    assert captured["cache_kwargs"]["agency_id"] == 12
    assert captured["cache_kwargs"]["actor_id"] == 21


def test_users_invites_post_creates_invite(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_user_invites

    monkeypatch.setattr(
        views_user_invites.registration_lifecycle,
        "create_user_invite",
        lambda *, actor, data: {
            "invite_id": "abc",
            "invite_code": "ABC123",
            "invite_email": "agent@example.com",
            "expires_at": "now",
            "status": "sent",
        },
    )
    request = APIRequestFactory().post(
        "/api/v1/users/invites/",
        {"email": "agent@example.com", "role": "agent", "manager_id": 21},
        format="json",
    )
    force_authenticate(request, user=_User())
    response = views_user_invites.users_invites(request)
    assert response.status_code == status.HTTP_201_CREATED


def test_users_invites_post_returns_503_when_email_queue_unavailable(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_user_invites

    def _raise_queue(*, actor, data):
        _ = actor, data
        raise views_user_invites.registration_lifecycle.EmailQueueUnavailableError(
            "queue unavailable"
        )

    monkeypatch.setattr(
        views_user_invites.registration_lifecycle,
        "create_user_invite",
        _raise_queue,
    )
    request = APIRequestFactory().post(
        "/api/v1/users/invites/",
        {"email": "agent@example.com", "role": "agent", "manager_id": 21},
        format="json",
    )
    force_authenticate(request, user=_User())
    response = views_user_invites.users_invites(request)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["code"] == "EMAIL_QUEUE_UNAVAILABLE"


def test_users_invites_resend_and_revoke(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_user_invites

    monkeypatch.setattr(
        views_user_invites.registration_lifecycle,
        "resend_invite",
        lambda *, actor, invite_id, expires_seconds=None: {"invite_id": invite_id},
    )
    monkeypatch.setattr(
        views_user_invites.registration_lifecycle,
        "revoke_invite",
        lambda *, actor, invite_id: {"status": "revoked", "invite_id": invite_id},
    )

    request_resend = APIRequestFactory().post(
        "/api/v1/users/invites/11111111-1111-1111-1111-111111111111/resend/",
        {},
        format="json",
    )
    force_authenticate(request_resend, user=_User())
    response_resend = views_user_invites.users_invite_resend(
        request_resend,
        invite_id="11111111-1111-1111-1111-111111111111",
    )
    assert response_resend.status_code == status.HTTP_200_OK

    request_revoke = APIRequestFactory().post(
        "/api/v1/users/invites/11111111-1111-1111-1111-111111111111/revoke/",
        {},
        format="json",
    )
    force_authenticate(request_revoke, user=_User())
    response_revoke = views_user_invites.users_invite_revoke(
        request_revoke,
        invite_id="11111111-1111-1111-1111-111111111111",
    )
    assert response_revoke.status_code == status.HTTP_200_OK


def test_users_invites_resend_returns_503_when_email_queue_unavailable(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_user_invites

    def _raise_queue(*, actor, invite_id, expires_seconds=None):
        _ = actor, invite_id, expires_seconds
        raise views_user_invites.registration_lifecycle.EmailQueueUnavailableError(
            "queue unavailable"
        )

    monkeypatch.setattr(
        views_user_invites.registration_lifecycle,
        "resend_invite",
        _raise_queue,
    )

    request_resend = APIRequestFactory().post(
        "/api/v1/users/invites/11111111-1111-1111-1111-111111111111/resend/",
        {},
        format="json",
    )
    force_authenticate(request_resend, user=_User())
    response = views_user_invites.users_invite_resend(
        request_resend,
        invite_id="11111111-1111-1111-1111-111111111111",
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["code"] == "EMAIL_QUEUE_UNAVAILABLE"
