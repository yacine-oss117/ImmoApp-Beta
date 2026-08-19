from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _User:
    id: int = 7
    pk: int = 7
    username: str = "agent-user"
    role: str = "manager"
    is_owner: bool = True
    is_superuser: bool = False
    agency_id: int | None = 12
    is_authenticated: bool = True


def test_matches_expand_demande_enqueues_canonical_async_identity(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    monkeypatch.setattr("server.async_task_identity.get_current_schema", lambda: "public")
    monkeypatch.setattr("server.async_task_identity.get_correlation_id", lambda: "corr-expand")

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        views_matches.expand_match_pairs_for_demande,
        "delay",
        lambda demande_id, **kwargs: captured.update(
            {
                "demande_id": demande_id,
                "kwargs": dict(kwargs),
            }
        )
        or SimpleNamespace(id="expand-1"),
    )
    monkeypatch.setattr(views_matches, "register_task", lambda *args, **kwargs: None)

    request = APIRequestFactory().post("/api/v1/matches/demandes/41/expand/", {}, format="json")
    force_authenticate(request, user=_User())

    response = views_matches.matches_expand_demande(request, 41)

    assert response.status_code == 200
    assert response.data == {"task_id": "expand-1"}
    assert captured == {
        "demande_id": 41,
        "kwargs": {
            "schema": "public",
            "agency_id": 12,
            "correlation_id": "corr-expand",
            "actor_id": 7,
            "actor_role": "manager",
        },
    }
