from __future__ import annotations

from pathlib import Path


def test_flush_email_outbox_task_is_scheduled() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    assert '"flush-email-outbox"' in text
    assert '"task": "flush_email_outbox"' in text
    assert '"schedule": 30.0' in text
