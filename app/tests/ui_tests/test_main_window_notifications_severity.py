from __future__ import annotations

import pytest
from PySide6.QtWidgets import QToolButton

from app.main_window_notifications import MainWindowNotificationsMixin

pytestmark = pytest.mark.ui


class _DummyToastManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def show_toast(
        self, title: str, body: str, *, severity: str = "info", duration_ms: int = 5000
    ) -> None:
        self.calls.append(
            {
                "title": title,
                "body": body,
                "severity": severity,
                "duration_ms": str(duration_ms),
            }
        )


class _Host(MainWindowNotificationsMixin):
    def __init__(self) -> None:
        self._toast_manager = _DummyToastManager()
        self._notification_unread = 0
        self._notifications_button = QToolButton()

    def _update_notification_badge(self) -> None:
        pass


def test_main_window_notification_handler_maps_event_type_to_severity(qapp) -> None:
    host = _Host()
    host._handle_notification({"type": "sync.failed", "title": "A", "body": "B"})
    host._handle_notification({"type": "registration.approved", "title": "C", "body": "D"})
    host._handle_notification({"type": "security.alert", "title": "E", "body": "F"})
    host._handle_notification({"type": "digest.info", "title": "G", "body": "H"})

    severities = [call["severity"] for call in host._toast_manager.calls]
    assert severities == ["error", "success", "warning", "info"]
