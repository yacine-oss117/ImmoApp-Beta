from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    pytest.importorskip(
        "daphne",
        reason="match-all kill-switch tests require server deps",
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _User:
    id: int = 7
    pk: int = 7
    username: str = "owner"
    role: str = "admin"
    is_owner: bool = True
    is_superuser: bool = True
    agency_id: int | None = 42
    is_authenticated: bool = True


def test_match_all_endpoints_respect_runtime_kill_switch(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    monkeypatch.setenv("IMMOAPP_DISABLE_MATCH_ALL_ENDPOINTS", "1")

    def _unexpected_schedule(*args, **kwargs):
        raise AssertionError("scheduler should not be called when kill switch is active")

    monkeypatch.setattr(
        views_matches.match_all_scheduler,
        "schedule_tenant_fair_task",
        _unexpected_schedule,
    )

    factory = APIRequestFactory()
    request = factory.post("/api/v1/matches/clients/all/", {}, format="json")
    force_authenticate(request, user=_User())

    response = views_matches.matches_count_all_clients(request)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["code"] == "MATCH_ALL_DISABLED"


def test_match_all_endpoints_use_degraded_safe_admission(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    monkeypatch.delenv("IMMOAPP_DISABLE_MATCH_ALL_ENDPOINTS", raising=False)
    monkeypatch.setattr(
        views_matches.work_admission,
        "admit_match_all",
        lambda **_kwargs: SimpleNamespace(
            allowed=False,
            retry_after=9,
            degraded=True,
            runtime_profile="red",
            admission_mode="degraded",
            pressure_reason="degraded_match_all_fallback",
            fair_share_limit=1,
        ),
    )

    factory = APIRequestFactory()
    request = factory.post("/api/v1/matches/clients/all/", {"agency_id": 42}, format="json")
    force_authenticate(request, user=_User())

    response = views_matches.matches_count_all_clients(request)
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.data["admission_mode"] == "degraded"
    assert response.data["runtime_profile"] == "red"
    assert response.data["fair_share_limit"] == 1


def test_match_all_endpoints_require_explicit_target_agency_for_superuser(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_matches

    monkeypatch.delenv("IMMOAPP_DISABLE_MATCH_ALL_ENDPOINTS", raising=False)
    monkeypatch.setattr(
        views_matches.work_admission,
        "admit_match_all",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("admission must not run")),
    )
    monkeypatch.setattr(
        views_matches.match_all_scheduler,
        "schedule_tenant_fair_task",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("scheduler must not run")),
    )

    factory = APIRequestFactory()
    request = factory.post("/api/v1/matches/clients/all/", {}, format="json")
    force_authenticate(request, user=_User(agency_id=None))

    response = views_matches.matches_count_all_clients(request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_match_all_endpoints_schedule_explicit_target_agency_without_fake_zero(
    monkeypatch,
) -> None:
    _ensure_django()
    from server.api import views_matches

    monkeypatch.delenv("IMMOAPP_DISABLE_MATCH_ALL_ENDPOINTS", raising=False)
    monkeypatch.setattr("server.async_task_identity.get_current_schema", lambda: "public")
    monkeypatch.setattr("server.async_task_identity.get_correlation_id", lambda: "corr-55")

    admitted: list[dict[str, object]] = []
    scheduled: list[dict[str, object]] = []
    enqueued: list[dict[str, object]] = []

    monkeypatch.setattr(
        views_matches.work_admission,
        "admit_match_all",
        lambda **kwargs: admitted.append(dict(kwargs))
        or SimpleNamespace(
            allowed=True,
            retry_after=9,
            degraded=False,
            runtime_profile="yellow",
            admission_mode="normal",
            pressure_reason="",
            fair_share_limit=1,
        ),
    )
    monkeypatch.setattr(
        views_matches.count_matches_all_clients_task,
        "apply_async",
        lambda **kwargs: enqueued.append(dict(kwargs)) or SimpleNamespace(id="task-55"),
    )

    def _schedule(**kwargs):
        scheduled.append({k: v for k, v in kwargs.items() if k != "launch_task"})
        launched = kwargs["launch_task"]()
        return {
            "status": "scheduled",
            "task_id": getattr(launched, "id", ""),
            "state": "queued",
        }

    monkeypatch.setattr(
        views_matches.match_all_scheduler,
        "schedule_tenant_fair_task",
        _schedule,
    )
    monkeypatch.setattr(views_matches, "register_task", lambda *args, **kwargs: None)

    factory = APIRequestFactory()
    request = factory.post("/api/v1/matches/clients/all/", {"agency_id": 55}, format="json")
    force_authenticate(request, user=_User(agency_id=None))

    response = views_matches.matches_count_all_clients(request)

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert admitted == [
        {
            "agency_id": 55,
            "task_name": "matches_all",
            "default_limit": 1,
            "retry_after_seconds": 10,
        }
    ]
    assert scheduled == [
        {
            "task_name": "matches_all",
            "stream_key": "clients:all",
            "agency_id": 55,
            "lease_seconds": 1800,
            "max_in_flight": 1,
        }
    ]
    assert enqueued == [
        {
            "kwargs": {
                "schema": "public",
                "agency_id": 55,
                "correlation_id": "corr-55",
                "actor_id": 7,
                "actor_role": "admin",
            },
            "queue": "rebuild_batch",
        }
    ]
