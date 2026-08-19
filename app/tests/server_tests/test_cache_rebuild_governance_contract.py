from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

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
    id: int = 7
    pk: int = 7
    username: str = "agent-user"
    role: str = "agent"
    is_owner: bool = False
    is_superuser: bool = False
    agency_id: int = 12
    is_authenticated: bool = True


def test_match_cache_rebuild_all_requires_owner() -> None:
    _ensure_django()
    from server.api import views_cache_tasks

    request = APIRequestFactory().post("/api/v1/cache/match/rebuild/", {}, format="json")
    force_authenticate(request, user=_User(is_owner=False, role="manager"))
    response = views_cache_tasks.match_cache_rebuild_all(request)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_enqueue_rebuild_passes_canonical_async_identity_payload(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_cache_tasks
    from server.services.rebuild_leases import LeaseReserveResult

    request = APIRequestFactory().post("/api/v1/cache/match/rebuild/", {}, format="json")
    user = _User(is_owner=True, role="manager")
    force_authenticate(request, user=user)
    request.user = user

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "server.async_task_identity.get_current_schema",
        lambda: "public",
    )
    monkeypatch.setattr(
        "server.async_task_identity.get_correlation_id",
        lambda: "corr-1",
    )
    monkeypatch.setattr(
        views_cache_tasks.rebuild_leases,
        "reserve_rebuild_lease_tx",
        lambda **kwargs: LeaseReserveResult(
            outcome="accepted",
            task_id=str(kwargs["task_id"]),
            retry_after_seconds=30,
        ),
    )
    monkeypatch.setattr(views_cache_tasks, "register_task", lambda *args, **kwargs: None)

    response = views_cache_tasks._enqueue_rebuild(
        request=request,
        job_type="dirty",
        scope_key="_",
        enqueue=lambda task_id, task_identity: captured.update(
            {
                "task_id": task_id,
                "task_identity": dict(task_identity),
            }
        )
        or SimpleNamespace(id=task_id),
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert captured["task_identity"] == {
        "schema": "public",
        "agency_id": 12,
        "correlation_id": "corr-1",
        "actor_id": 7,
        "actor_role": "manager",
    }
    assert captured["task_id"] == response.data["task_id"]


def test_enqueue_rebuild_returns_coalesced_contract(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_cache_tasks
    from server.services.rebuild_leases import LeaseReserveResult

    request = APIRequestFactory().post("/api/v1/cache/match/rebuild/", {}, format="json")
    user = _User(is_owner=True, role="manager")
    force_authenticate(request, user=user)
    request.user = user

    monkeypatch.setattr(
        views_cache_tasks.rebuild_leases,
        "reserve_rebuild_lease_tx",
        lambda **kwargs: LeaseReserveResult(
            outcome="coalesced",
            task_id="coalesced-task",
            retry_after_seconds=42,
        ),
    )
    monkeypatch.setattr(
        views_cache_tasks.tenant_resource_governor,
        "allow_expensive_work",
        lambda **_kwargs: (True, 30),
    )
    monkeypatch.setattr(views_cache_tasks, "register_task", lambda *args, **kwargs: None)

    response = views_cache_tasks._enqueue_rebuild(
        request=request,
        job_type="all",
        scope_key="_",
        enqueue=lambda _task_id, _task_identity: object(),
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.data["coalesced"] is True
    assert response.data["task_id"] == "coalesced-task"
    assert response["Retry-After"] == "42"


def test_enqueue_rebuild_returns_backpressure_contract(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_cache_tasks
    from server.services.rebuild_leases import LeaseReserveResult

    request = APIRequestFactory().post("/api/v1/cache/match/rebuild/", {}, format="json")
    user = _User(is_owner=True, role="manager")
    force_authenticate(request, user=user)
    request.user = user

    monkeypatch.setattr(
        views_cache_tasks.rebuild_leases,
        "reserve_rebuild_lease_tx",
        lambda **kwargs: LeaseReserveResult(
            outcome="backpressured",
            task_id=None,
            retry_after_seconds=35,
        ),
    )
    monkeypatch.setattr(
        views_cache_tasks.tenant_resource_governor,
        "allow_expensive_work",
        lambda **_kwargs: (True, 30),
    )

    response = views_cache_tasks._enqueue_rebuild(
        request=request,
        job_type="all",
        scope_key="_",
        enqueue=lambda _task_id, _task_identity: object(),
    )
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.data["code"] == "REBUILD_BACKPRESSURE"
    assert response["Retry-After"] == "35"


def test_enqueue_rebuild_backpressure_emits_alert_and_metric(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_cache_tasks
    from server.services.rebuild_leases import LeaseReserveResult

    request = APIRequestFactory().post("/api/v1/cache/match/rebuild/", {}, format="json")
    user = _User(is_owner=True, role="manager")
    force_authenticate(request, user=user)
    request.user = user

    monkeypatch.setattr(
        views_cache_tasks.rebuild_leases,
        "reserve_rebuild_lease_tx",
        lambda **kwargs: LeaseReserveResult(
            outcome="backpressured",
            task_id=None,
            retry_after_seconds=30,
        ),
    )
    monkeypatch.setattr(
        views_cache_tasks.tenant_resource_governor,
        "allow_expensive_work",
        lambda **_kwargs: (True, 30),
    )
    metric_calls: list[dict[str, object]] = []
    alert_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        views_cache_tasks,
        "record_queue_saturation",
        lambda **kwargs: metric_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        views_cache_tasks.auth_security_alerts,
        "emit_security_alert",
        lambda **kwargs: alert_calls.append(dict(kwargs)),
    )

    response = views_cache_tasks._enqueue_rebuild(
        request=request,
        job_type="dirty",
        scope_key="_",
        enqueue=lambda _task_id, _task_identity: object(),
    )
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert metric_calls == [{"queue": "rebuild_batch", "outcome": "backpressured"}]
    assert len(alert_calls) == 1
    assert alert_calls[0]["reason_code"] == "rebuild_queue_saturation"
