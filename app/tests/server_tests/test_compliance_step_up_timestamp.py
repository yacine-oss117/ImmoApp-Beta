from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _OwnerUser:
    id: int = 11
    pk: int = 11
    is_authenticated: bool = True
    is_owner: bool = True
    is_superuser: bool = False
    role: str = "manager"
    agency_id: int = 5


def test_compliance_export_uses_step_up_iat_for_verification_time(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_compliance
    from server.api.tasks_compliance import run_compliance_export_task

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        views_compliance,
        "parse_step_up_claims",
        lambda _req: ({"uid": 11, "iat": 1_700_000_000}, None),
    )

    def _create_export_job(**kwargs):
        captured["step_up_verified_at"] = kwargs.get("step_up_verified_at")
        return {
            "job_id": "11111111-1111-1111-1111-111111111111",
            "status": "queued",
            "job_type": "export",
        }

    monkeypatch.setattr(views_compliance.compliance_jobs, "create_export_job", _create_export_job)
    monkeypatch.setattr(run_compliance_export_task, "delay", lambda *_args, **_kwargs: None)

    request = APIRequestFactory().post(
        "/api/v1/compliance/users/12/export/",
        {"reason": "subject access"},
        format="json",
    )
    force_authenticate(request, user=_OwnerUser())

    response = views_compliance.compliance_user_export(request, user_id=12)
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert captured["step_up_verified_at"] == datetime.fromtimestamp(1_700_000_000, tz=UTC)


def test_compliance_delete_uses_step_up_iat_for_verification_time(monkeypatch) -> None:
    _ensure_django()
    from server.api import views_compliance
    from server.api.tasks_compliance import run_compliance_delete_task

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        views_compliance,
        "parse_step_up_claims",
        lambda _req: ({"uid": 11, "iat": 1_700_000_001}, None),
    )

    def _create_delete_job(**kwargs):
        captured["step_up_verified_at"] = kwargs.get("step_up_verified_at")
        return {
            "job_id": "22222222-2222-2222-2222-222222222222",
            "status": "queued",
            "job_type": "delete",
        }

    monkeypatch.setattr(views_compliance.compliance_jobs, "create_delete_job", _create_delete_job)
    monkeypatch.setattr(run_compliance_delete_task, "delay", lambda *_args, **_kwargs: None)

    request = APIRequestFactory().post(
        "/api/v1/compliance/users/12/delete/",
        {"reason": "privacy request"},
        format="json",
    )
    force_authenticate(request, user=_OwnerUser())

    response = views_compliance.compliance_user_delete(request, user_id=12)
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert captured["step_up_verified_at"] == datetime.fromtimestamp(1_700_000_001, tz=UTC)


def test_compliance_view_does_not_use_now_for_step_up_proof_timestamp() -> None:
    text = Path("server/api/views_compliance.py").read_text(encoding="utf-8")
    assert "step_up_iat_to_datetime" in text
    assert "step_up_verified_at=timezone.now()" not in text
