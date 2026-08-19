from __future__ import annotations

import os
from pathlib import Path


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def test_send_platform_email_queues_message(monkeypatch) -> None:
    _ensure_django()
    from server.services import email_sender

    queued: dict[str, str] = {}

    def _queue_email(*, to: str, subject: str, body_text: str, body_html: str = "") -> None:
        queued["to"] = to
        queued["subject"] = subject
        queued["body_text"] = body_text
        queued["body_html"] = body_html

    monkeypatch.setattr(email_sender, "queue_email", _queue_email)
    ok = email_sender.send_platform_email(
        to="owner@example.com",
        subject="Welcome",
        body_text="hello",
        body_html="<p>hello</p>",
    )
    assert ok is True
    assert queued["to"] == "owner@example.com"


def test_flush_outbox_contract_uses_skip_locked_and_cleanup() -> None:
    text = Path("server/services/email_sender.py").read_text(encoding="utf-8")
    assert "select_for_update(skip_locked=True)" in text
    assert '_STATUS_SENDING = "sending"' in text
    assert "status=EmailOutbox.STATUS_PENDING" in text
    assert "status=_STATUS_SENDING" in text
    assert "status=EmailOutbox.STATUS_FAILED_PERMANENT" in text
    assert "status__in=(EmailOutbox.STATUS_SENT, EmailOutbox.STATUS_FAILED_PERMANENT)" in text
    assert "Email outbox recovered stale delivery claims=" in text


def test_flush_outbox_logs_permanent_failures() -> None:
    text = Path("server/services/email_sender.py").read_text(encoding="utf-8")
    assert "Email permanently failed:" in text
