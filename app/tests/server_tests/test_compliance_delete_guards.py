from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _mock_common_success_path(monkeypatch, compliance_jobs) -> None:
    monkeypatch.setattr(compliance_jobs.transaction, "atomic", lambda *_, **__: nullcontext())
    monkeypatch.setattr(compliance_jobs, "_existing_active_job", lambda **_kwargs: None)
    monkeypatch.setattr(compliance_jobs, "_serialize_job", lambda _row: {"status": "queued"})
    monkeypatch.setattr(compliance_jobs.auth_events, "log_auth_event", lambda **_kwargs: None)

    class _Manager:
        @staticmethod
        def create(**_kwargs):
            return SimpleNamespace(job_id="11111111-1111-1111-1111-111111111111")

    monkeypatch.setattr(compliance_jobs.ComplianceJob, "objects", _Manager(), raising=False)


def test_compliance_delete_self_guard_rejects_self_delete(monkeypatch) -> None:
    _ensure_django()
    from server.services import compliance_jobs
    from server.services.errors import PermissionDeniedError

    actor = SimpleNamespace(id=11, agency_id=7, is_owner=True, is_superuser=False)
    target = SimpleNamespace(id=11, agency_id=7, is_owner=False)
    monkeypatch.setattr(compliance_jobs, "require_owner", lambda _actor: None)
    monkeypatch.setattr(compliance_jobs, "_resolve_target_user", lambda _actor, _uid: target)

    with pytest.raises(PermissionDeniedError):
        compliance_jobs._create_job(
            actor=actor,
            target_user_id=11,
            job_type=compliance_jobs.ComplianceJob.TYPE_DELETE,
            step_up_verified_at="2026-01-01T00:00:00Z",
        )


def test_compliance_delete_last_owner_guard_rejects(monkeypatch) -> None:
    _ensure_django()
    from server.services import compliance_jobs
    from server.services.errors import PermissionDeniedError

    actor = SimpleNamespace(id=10, agency_id=7, is_owner=True, is_superuser=False)
    target = SimpleNamespace(id=12, agency_id=7, is_owner=True)
    monkeypatch.setattr(compliance_jobs, "require_owner", lambda _actor: None)
    monkeypatch.setattr(compliance_jobs, "_resolve_target_user", lambda _actor, _uid: target)

    class _CountQuery:
        @staticmethod
        def count() -> int:
            return 1

    class _Objects:
        @staticmethod
        def filter(**_kwargs):
            return _CountQuery()

    class _UserModel:
        objects = _Objects()

    monkeypatch.setattr(compliance_jobs, "get_user_model", lambda: _UserModel)

    with pytest.raises(PermissionDeniedError):
        compliance_jobs._create_job(
            actor=actor,
            target_user_id=12,
            job_type=compliance_jobs.ComplianceJob.TYPE_DELETE,
            step_up_verified_at="2026-01-01T00:00:00Z",
        )


def test_compliance_delete_non_owner_user_succeeds(monkeypatch) -> None:
    _ensure_django()
    from server.services import compliance_jobs

    actor = SimpleNamespace(id=10, agency_id=7, is_owner=True, is_superuser=False)
    target = SimpleNamespace(id=12, agency_id=7, is_owner=False)
    monkeypatch.setattr(compliance_jobs, "require_owner", lambda _actor: None)
    monkeypatch.setattr(compliance_jobs, "_resolve_target_user", lambda _actor, _uid: target)
    _mock_common_success_path(monkeypatch, compliance_jobs)

    result = compliance_jobs._create_job(
        actor=actor,
        target_user_id=12,
        job_type=compliance_jobs.ComplianceJob.TYPE_DELETE,
        step_up_verified_at="2026-01-01T00:00:00Z",
    )
    assert result["status"] == "queued"


def test_compliance_delete_owner_with_another_owner_succeeds(monkeypatch) -> None:
    _ensure_django()
    from server.services import compliance_jobs

    actor = SimpleNamespace(id=10, agency_id=7, is_owner=True, is_superuser=False)
    target = SimpleNamespace(id=12, agency_id=7, is_owner=True)
    monkeypatch.setattr(compliance_jobs, "require_owner", lambda _actor: None)
    monkeypatch.setattr(compliance_jobs, "_resolve_target_user", lambda _actor, _uid: target)

    class _CountQuery:
        @staticmethod
        def count() -> int:
            return 2

    class _Objects:
        @staticmethod
        def filter(**_kwargs):
            return _CountQuery()

    class _UserModel:
        objects = _Objects()

    monkeypatch.setattr(compliance_jobs, "get_user_model", lambda: _UserModel)
    _mock_common_success_path(monkeypatch, compliance_jobs)

    result = compliance_jobs._create_job(
        actor=actor,
        target_user_id=12,
        job_type=compliance_jobs.ComplianceJob.TYPE_DELETE,
        step_up_verified_at="2026-01-01T00:00:00Z",
    )
    assert result["status"] == "queued"


def test_compliance_export_allows_self_target(monkeypatch) -> None:
    _ensure_django()
    from server.services import compliance_jobs

    actor = SimpleNamespace(id=11, agency_id=7, is_owner=True, is_superuser=False)
    target = SimpleNamespace(id=11, agency_id=7, is_owner=True)
    monkeypatch.setattr(compliance_jobs, "require_owner", lambda _actor: None)
    monkeypatch.setattr(compliance_jobs, "_resolve_target_user", lambda _actor, _uid: target)
    _mock_common_success_path(monkeypatch, compliance_jobs)

    result = compliance_jobs._create_job(
        actor=actor,
        target_user_id=11,
        job_type=compliance_jobs.ComplianceJob.TYPE_EXPORT,
        step_up_verified_at="2026-01-01T00:00:00Z",
    )
    assert result["status"] == "queued"
