from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _patch_accept_invite_dependencies(monkeypatch, module) -> None:
    monkeypatch.setattr(module.transaction, "atomic", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        module, "_resolve_ale_text", lambda public_value, encrypted_value: public_value
    )
    monkeypatch.setattr(module, "apply_user_ale", lambda payload, changed_fields=None: None)
    monkeypatch.setattr(module, "validate_password", lambda password, user=None: None)
    monkeypatch.setattr(module.auth_events, "log_auth_event", lambda **kwargs: None)
    monkeypatch.setattr(module, "agency_id_of", lambda _user: 11)
    monkeypatch.setattr(module, "serialize_user", lambda _user: {"id": int(_user.id)})
    monkeypatch.setattr(
        module.registration_invites,
        "_bump_invite_generations_in_atomic",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        module.registration_invites,
        "_bump_users_generation_in_atomic",
        lambda **_kwargs: None,
    )

    class _UserObjects:
        def filter(self, **kwargs):
            return self

        def exists(self) -> bool:
            return False

    class _User:
        objects = _UserObjects()

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.id = 88

        def set_password(self, _password: str) -> None:
            return

        def full_clean(self) -> None:
            return

        def save(self) -> None:
            return

    monkeypatch.setattr(module, "get_user_model", lambda: _User)


def _invite_objects(rows: list[SimpleNamespace]):
    class _InviteQuery:
        def __init__(self, current_rows: list[SimpleNamespace]):
            self._rows = list(current_rows)

        def select_for_update(self):
            return self

        def select_related(self, *_args):
            return self

        def filter(self, **kwargs):
            filtered = list(self._rows)
            for key, value in kwargs.items():
                if key == "invite_email__iexact":
                    filtered = [
                        row
                        for row in filtered
                        if str(getattr(row, "invite_email", "")).lower() == str(value).lower()
                    ]
                elif key == "invite_code_hash":
                    filtered = [
                        row for row in filtered if getattr(row, "invite_code_hash", None) == value
                    ]
                elif key == "status":
                    filtered = [row for row in filtered if getattr(row, "status", None) == value]
                elif key == "expires_at__gt":
                    filtered = [row for row in filtered if row.expires_at > value]
                else:
                    raise AssertionError(f"Unexpected invite filter: {key}")
            return _InviteQuery(filtered)

        def order_by(self, *fields):
            ordered = list(self._rows)
            for field in reversed(fields):
                reverse = field.startswith("-")
                name = field[1:] if reverse else field
                ordered.sort(key=lambda row: getattr(row, name), reverse=reverse)
            return _InviteQuery(ordered)

        def first(self):
            return self._rows[0] if self._rows else None

    return _InviteQuery(rows)


def test_registration_approval_emits_user_and_agency_notifications(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module

    monkeypatch.setattr(module.transaction, "atomic", lambda *args, **kwargs: nullcontext())

    record = SimpleNamespace(
        status=module.RegistrationRequest.STATUS_PENDING,
        expires_at=timezone.now() + timedelta(days=1),
        approval_token_hash="",
        activation_code_hash="",
        activation_code_expires_at=None,
        owner_email="owner@example.com",
        reviewed_at=None,
    )
    record.save = lambda *args, **kwargs: None
    monkeypatch.setattr(
        module,
        "_load_registration_for_signed_token",
        lambda *, signed_token, for_update=True: record,
    )

    plaintext = {
        "agency_name": "Acme",
        "legal_name": "Acme SARL",
        "registry_number": "R-123",
        "agency_address": "1 Main Street",
        "agency_city": "Algiers",
        "agency_postal_code": "16000",
        "owner_first_name": "Fatima",
        "owner_last_name": "Agent",
        "owner_phone": "+213600000001",
    }
    monkeypatch.setattr(
        module, "_registration_plain", lambda _record, field_name: plaintext[field_name]
    )
    agency_ale_agency_ids: list[int | None] = []
    monkeypatch.setattr(
        module,
        "apply_agency_ale",
        lambda payload, changed_fields=None, agency_id=None: agency_ale_agency_ids.append(
            agency_id
        ),
    )
    monkeypatch.setattr(
        module,
        "apply_user_ale",
        lambda payload, changed_fields=None, agency_id=None: None,
    )

    class _AgencyObjects:
        @staticmethod
        def create(**kwargs):
            agency = SimpleNamespace(id=7, display_name=str(kwargs.get("display_name") or "Acme"))
            agency.save = lambda **kwargs: None
            return agency

    monkeypatch.setattr(module.Agency, "objects", _AgencyObjects(), raising=False)

    class _Owner:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.id = 41

        def set_unusable_password(self) -> None:
            return

        def full_clean(self) -> None:
            return

        def save(self) -> None:
            return

    monkeypatch.setattr(module, "get_user_model", lambda: _Owner)

    class _ServiceFilter:
        def exclude(self, **kwargs):
            return self

        def exists(self) -> bool:
            return True

    class _ServiceObjects:
        @staticmethod
        def filter(**kwargs):
            return _ServiceFilter()

    class _ServiceUserModel:
        objects = _ServiceObjects()

    monkeypatch.setattr(module, "get_user_model_for_service", lambda: _ServiceUserModel)
    monkeypatch.setattr(
        module, "build_owner_welcome_email", lambda **kwargs: ("s", "t", "<p>h</p>")
    )
    monkeypatch.setattr(module, "send_platform_email", lambda **kwargs: True)
    monkeypatch.setattr("server.pg.uow.use_security_context", lambda **kwargs: nullcontext())

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(module, "_safe_record_and_notify", lambda **kwargs: calls.append(kwargs))

    result = module.approve_registration_by_token(signed_token="signed")
    assert result["status"] == "approved"
    assert agency_ale_agency_ids == [7]
    assert any(call.get("scope") == "user" for call in calls)
    assert any(call.get("scope") == "agency" for call in calls)
    assert all(call.get("event_type") == "registration.approved" for call in calls)


def test_activate_owner_emits_team_joined_notification(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module

    monkeypatch.setattr(module.transaction, "atomic", lambda *args, **kwargs: nullcontext())

    record = SimpleNamespace(
        activation_code_hash=module._sha256(
            "ABCDEFGH"
        ),  # noqa: SLF001 - deterministic hash fixture
        activation_code_expires_at=timezone.now() + timedelta(hours=2),
    )
    record.save = lambda *args, **kwargs: None

    class _RegObjects:
        def select_for_update(self):
            return self

        def filter(self, **kwargs):
            return self

        def first(self):
            return record

    monkeypatch.setattr(module.RegistrationRequest, "objects", _RegObjects(), raising=False)

    user = SimpleNamespace(
        id=77,
        email="owner@example.com",
        first_name="Fatima",
        last_name="Agent",
        is_active=False,
        agency_id=11,
    )
    user.set_password = lambda _password: None
    user.full_clean = lambda: None
    user.save = lambda **kwargs: None

    class _UserObjects:
        def select_for_update(self):
            return self

        def filter(self, **kwargs):
            return self

        def first(self):
            return user

    class _UserModel:
        objects = _UserObjects()

    monkeypatch.setattr(module, "get_user_model_for_service", lambda: _UserModel)
    monkeypatch.setattr(module, "validate_password", lambda password, user=None: None)
    monkeypatch.setattr(
        module, "_issue_auth_tokens", lambda **kwargs: {"access": "a", "refresh": "r"}
    )
    monkeypatch.setattr(module.auth_events, "log_auth_event", lambda **kwargs: None)
    monkeypatch.setattr(module, "serialize_user", lambda _user: {"id": int(_user.id)})
    monkeypatch.setattr(module, "agency_id_of", lambda _user: 11)
    monkeypatch.setattr("server.pg.uow.use_security_context", lambda **kwargs: nullcontext())

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(module, "_safe_record_and_notify", lambda **kwargs: calls.append(kwargs))

    result = module.activate_owner(
        email="owner@example.com",
        activation_code="abcdefgh",
        password="StrongPassword!123",
        source_ip=None,
        user_agent=None,
        request_id=None,
    )
    assert result["status"] == "activated"
    assert any(call.get("event_type") == "team.member_joined" for call in calls)
    assert any(call.get("scope") == "agency" for call in calls)


def test_accept_invite_uses_issue_auth_tokens_compatibility_seam(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module

    now = timezone.now()
    invite = SimpleNamespace(
        id=1,
        role="manager",
        manager_id=None,
        agency_id=11,
        agency=SimpleNamespace(display_name="Acme"),
        invite_email="invitee@example.com",
        invite_name="Invited User",
        invite_name_enc="",
        invite_code_hash=module._sha256("ABC123"),
        status=module.UserInvite.STATUS_PENDING,
        created_at=now,
        expires_at=now + timedelta(hours=2),
        accepted_at=None,
        accepted_user=None,
    )
    invite.save = lambda *args, **kwargs: None

    monkeypatch.setattr(module.UserInvite, "objects", _invite_objects([invite]), raising=False)
    _patch_accept_invite_dependencies(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "_issue_auth_tokens",
        lambda **kwargs: {"access": "patched-access", "refresh": "patched-refresh"},
    )

    result = module.accept_invite(
        invite_code="abc123",
        email="invitee@example.com",
        password="StrongPassword!123",
        source_ip=None,
        user_agent=None,
        request_id=None,
    )

    assert result["status"] == "accepted"
    assert result["tokens"] == {"access": "patched-access", "refresh": "patched-refresh"}


def test_accept_invite_matches_exact_pending_code_when_same_email_has_multiple_invites(
    monkeypatch,
) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module

    now = timezone.now()
    first_invite = SimpleNamespace(
        id=1,
        role="manager",
        manager_id=None,
        agency_id=11,
        agency=SimpleNamespace(display_name="Acme"),
        invite_email="invitee@example.com",
        invite_name="First Invite",
        invite_name_enc="",
        invite_code_hash=module._sha256("FIRST1"),
        status=module.UserInvite.STATUS_PENDING,
        created_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=2),
        accepted_at=None,
        accepted_user=None,
    )
    second_invite = SimpleNamespace(
        id=2,
        role="manager",
        manager_id=None,
        agency_id=11,
        agency=SimpleNamespace(display_name="Acme"),
        invite_email="invitee@example.com",
        invite_name="Second Invite",
        invite_name_enc="",
        invite_code_hash=module._sha256("SECOND"),
        status=module.UserInvite.STATUS_PENDING,
        created_at=now,
        expires_at=now + timedelta(hours=2),
        accepted_at=None,
        accepted_user=None,
    )
    first_invite.save = lambda *args, **kwargs: None
    second_invite.save = lambda *args, **kwargs: None

    monkeypatch.setattr(
        module.UserInvite,
        "objects",
        _invite_objects([first_invite, second_invite]),
        raising=False,
    )
    _patch_accept_invite_dependencies(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "_issue_auth_tokens",
        lambda **kwargs: {"access": "patched-access", "refresh": "patched-refresh"},
    )

    result = module.accept_invite(
        invite_code="second",
        email="invitee@example.com",
        password="StrongPassword!123",
        source_ip=None,
        user_agent=None,
        request_id=None,
    )

    assert result["status"] == "accepted"
    assert result["tokens"] == {"access": "patched-access", "refresh": "patched-refresh"}
    assert first_invite.status == module.UserInvite.STATUS_PENDING
    assert second_invite.status == module.UserInvite.STATUS_ACCEPTED


def test_accept_invite_invalid_code_still_denies_without_disclosing(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module
    from server.services.errors import PermissionDeniedError

    now = timezone.now()
    first_invite = SimpleNamespace(
        id=1,
        role="manager",
        manager_id=None,
        agency_id=11,
        agency=SimpleNamespace(display_name="Acme"),
        invite_email="invitee@example.com",
        invite_name="First Invite",
        invite_name_enc="",
        invite_code_hash=module._sha256("FIRST1"),
        status=module.UserInvite.STATUS_PENDING,
        created_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=2),
        accepted_at=None,
        accepted_user=None,
    )
    second_invite = SimpleNamespace(
        id=2,
        role="manager",
        manager_id=None,
        agency_id=11,
        agency=SimpleNamespace(display_name="Acme"),
        invite_email="invitee@example.com",
        invite_name="Second Invite",
        invite_name_enc="",
        invite_code_hash=module._sha256("SECOND"),
        status=module.UserInvite.STATUS_PENDING,
        created_at=now,
        expires_at=now + timedelta(hours=2),
        accepted_at=None,
        accepted_user=None,
    )
    first_invite.save = lambda *args, **kwargs: None
    second_invite.save = lambda *args, **kwargs: None

    monkeypatch.setattr(
        module.UserInvite,
        "objects",
        _invite_objects([first_invite, second_invite]),
        raising=False,
    )
    _patch_accept_invite_dependencies(monkeypatch, module)

    with pytest.raises(PermissionDeniedError, match="Invalid invite code."):
        module.accept_invite(
            invite_code="nope99",
            email="invitee@example.com",
            password="StrongPassword!123",
            source_ip=None,
            user_agent=None,
            request_id=None,
        )


def test_accept_invite_exact_match_expired_path_remains_unchanged(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module
    from server.services.errors import PermissionDeniedError

    now = timezone.now()
    expired_invite = SimpleNamespace(
        id=2,
        role="manager",
        manager_id=None,
        agency_id=11,
        agency=SimpleNamespace(display_name="Acme"),
        invite_email="invitee@example.com",
        invite_name="Expired Invite",
        invite_name_enc="",
        invite_code_hash=module._sha256("SECOND"),
        status=module.UserInvite.STATUS_PENDING,
        created_at=now,
        expires_at=now - timedelta(minutes=1),
        accepted_at=None,
        accepted_user=None,
    )
    expired_invite.save = lambda *args, **kwargs: None

    monkeypatch.setattr(
        module.UserInvite,
        "objects",
        _invite_objects([expired_invite]),
        raising=False,
    )
    _patch_accept_invite_dependencies(monkeypatch, module)

    with pytest.raises(PermissionDeniedError, match="Invite code expired."):
        module.accept_invite(
            invite_code="second",
            email="invitee@example.com",
            password="StrongPassword!123",
            source_ip=None,
            user_agent=None,
            request_id=None,
        )

    assert expired_invite.status == module.UserInvite.STATUS_EXPIRED


def _patch_compliance_job_objects(monkeypatch, module, row) -> None:
    class _JobQuery:
        def __init__(self, job_row):
            self._row = job_row

        def filter(self, **kwargs):
            return self

        def first(self):
            return self._row

        def get(self, **kwargs):
            return self._row

    class _JobObjects:
        def __init__(self, job_row):
            self._query = _JobQuery(job_row)

        def select_for_update(self):
            return self._query

    monkeypatch.setattr(module.ComplianceJob, "objects", _JobObjects(row), raising=False)


@pytest.mark.parametrize(
    ("job_runner_name", "payload_builder_name"),
    (
        ("run_export_job", "_build_export_payload"),
        ("run_delete_job", "_run_delete"),
    ),
)
def test_compliance_job_runners_emit_success_and_failure_notifications(
    monkeypatch,
    job_runner_name: str,
    payload_builder_name: str,
) -> None:
    _ensure_django()
    from server.services import compliance_jobs as module

    monkeypatch.setattr(module.transaction, "atomic", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(module, "_mark_running", lambda row: None)
    monkeypatch.setattr(module, "_mark_succeeded", lambda row, **kwargs: None)
    monkeypatch.setattr(module, "_mark_failed", lambda row, **kwargs: None)
    monkeypatch.setattr(module, "_serialize_job", lambda row: {"status": str(row.status)})

    row = SimpleNamespace(
        id=9,
        job_id="j-1",
        status=module.ComplianceJob.STATUS_QUEUED,
        agency_id=5,
        requested_by_id=33,
        job_type=module.ComplianceJob.TYPE_EXPORT,
    )
    _patch_compliance_job_objects(monkeypatch, module, row)

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        module, "_emit_user_job_notification", lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setattr(module, payload_builder_name, lambda _row: {"ok": True})

    runner = getattr(module, job_runner_name)
    runner(job_id="j-1")
    assert any(call.get("event_type") == "compliance.job_completed" for call in calls)

    calls.clear()

    def _raise(_row):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, payload_builder_name, _raise)
    runner(job_id="j-1")
    assert any(call.get("event_type") == "compliance.job_failed" for call in calls)


def test_rebuild_match_cache_all_emits_ephemeral_notification(monkeypatch) -> None:
    _ensure_django()
    from server.api import tasks_match_cache as module

    monkeypatch.setattr(
        module, "require_agency_id", lambda agency_id, task_name: int(agency_id or 1)
    )
    monkeypatch.setattr(module, "match_compute_context", lambda *args, **kwargs: nullcontext())

    @contextmanager
    def _lock(*args, **kwargs):
        yield True

    monkeypatch.setattr(module, "match_cache_rebuild_lock", _lock)
    monkeypatch.setattr(module, "count_active_clients", lambda _session: 2)
    monkeypatch.setattr(module, "iter_active_client_batches", lambda _session, **kwargs: [[1, 2]])
    monkeypatch.setattr(
        module.match_counter,
        "batch_count_clients_paginated",
        lambda _session, batch: {int(client_id): 1 for client_id in batch},
    )
    monkeypatch.setattr(module, "store_counts", lambda _session, counts, *, label: len(counts))

    def _adaptive(items, process_fn, **kwargs):
        for item in items:
            process_fn(item)
        return len(items)

    monkeypatch.setattr(module, "adaptive_batch_process", _adaptive)

    class _SessionCtx:
        def __enter__(self):
            return SimpleNamespace()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Uow:
        @staticmethod
        def session():
            return _SessionCtx()

        @staticmethod
        def transaction():
            return _SessionCtx()

    monkeypatch.setattr("server.pg.uow.get_uow", lambda: _Uow())

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "server.api.notifications.notify_only", lambda **kwargs: calls.append(kwargs)
    )

    result = module.rebuild_match_cache_all(agency_id=1)
    assert result["clients"] == 2
    assert any(call.get("event_type") == "cache.rebuild_completed" for call in calls)
