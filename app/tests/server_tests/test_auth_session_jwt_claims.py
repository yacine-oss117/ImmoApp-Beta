from __future__ import annotations

import os
from types import SimpleNamespace


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def test_token_obtain_pair_serializer_embeds_account_scope_claims(monkeypatch) -> None:
    _ensure_django()
    from rest_framework_simplejwt.tokens import RefreshToken

    from server.api.auth_session_jwt import SessionAwareTokenObtainPairSerializer

    user = SimpleNamespace(
        id=7,
        pk=7,
        agency_id=11,
        role="manager",
        is_owner=True,
    )

    monkeypatch.setattr(
        SessionAwareTokenObtainPairSerializer.token_class,
        "for_user",
        classmethod(lambda cls, _user: RefreshToken()),
    )
    token = SessionAwareTokenObtainPairSerializer.get_token(user)

    assert int(token["agency_id"]) == 11
    assert int(token["user_id"]) == 7
    assert str(token["sub"]) == "7"
    assert str(token["role"]) == "manager"
    assert bool(token["is_owner"]) is True
