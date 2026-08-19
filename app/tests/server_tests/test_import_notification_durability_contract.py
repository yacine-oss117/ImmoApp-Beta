from __future__ import annotations

from pathlib import Path

import pytest
from django.db import DatabaseError

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.api.notifications import (  # noqa: E402
    NotificationPersistenceError,
    record_and_notify,
    record_notification_in_atomic,
)
from server.services.import_notifications import (  # noqa: E402
    record_import_success_notification,
)


def test_record_and_notify_persists_before_broadcast_and_keeps_durable_success_on_broadcast_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.api.notifications.record_notification",
        lambda **_kwargs: {
            "notification_id": 91,
            "payload": {"type": "import.execution_completed"},
        },
    )
    monkeypatch.setattr(
        "server.api.notifications.broadcast_notification_payload",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("ws offline")),
    )

    result = record_and_notify(
        scope="user",
        user_id=7,
        event_type="import.execution_completed",
        title="Import finished",
        body="Completed.",
        data={"session_id": "job-1"},
    )

    assert result["notification_id"] == 91
    assert result["payload"]["type"] == "import.execution_completed"


def test_record_notification_in_atomic_raises_specific_error_when_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.api.notifications.insert_notification_in_atomic",
        lambda **_kwargs: (_ for _ in ()).throw(DatabaseError("db unavailable")),
    )

    with pytest.raises(NotificationPersistenceError):
        record_notification_in_atomic(
            agency_id=7,
            scope="user",
            user_id=7,
            event_type="import.execution_completed",
            title="Import finished",
            body="Completed.",
            data={"session_id": "job-1"},
        )


def test_import_success_notification_returns_completed_and_propagates_persistence_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.services.import_notifications.record_and_notify_in_atomic",
        lambda **_kwargs: {"notification_id": 12, "payload": {"type": "ok"}},
    )

    completed = record_import_success_notification(
        agency_id=17,
        user_id=7,
        job_id="job-1",
        filename="clients.csv",
        entity_type="client",
        created_count=1,
        updated_count=0,
        error_count=0,
        review_total_count=0,
        review_overflow_count=0,
        review_pending_group_count=0,
    )

    assert completed == {
        "state": "completed",
        "reason_code": "",
        "recovery_owner": "",
    }

    monkeypatch.setattr(
        "server.services.import_notifications.record_and_notify_in_atomic",
        lambda **_kwargs: (_ for _ in ()).throw(NotificationPersistenceError("persist failed")),
    )

    with pytest.raises(NotificationPersistenceError):
        record_import_success_notification(
            agency_id=17,
            user_id=7,
            job_id="job-2",
            filename="clients.csv",
            entity_type="client",
            created_count=1,
            updated_count=0,
            error_count=0,
            review_total_count=0,
            review_overflow_count=0,
            review_pending_group_count=0,
        )


def test_import_notification_owner_has_no_importer_local_broad_exception_wrapper() -> None:
    source = Path("server/services/import_notifications.py").read_text(encoding="utf-8")

    assert "except Exception" not in source
    assert "except NotificationPersistenceError" not in source
    assert "notification_record_deferred" not in source
    assert "record_and_notify_in_atomic(" in source
