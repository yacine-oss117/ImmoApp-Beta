from __future__ import annotations

import pytest
from PySide6.QtWidgets import QProgressBar, QPushButton

from app.widgets.notification_toast import NotificationToast, ToastManager

pytestmark = pytest.mark.ui


def test_notification_toast_accepts_severity_and_widgets_exist(qapp) -> None:
    toast = NotificationToast("Title", "Body", severity="success", duration_ms=2000)
    assert toast.objectName() == "NotificationToast_success"
    assert toast.findChild(QPushButton, "notificationToastClose") is not None
    assert toast.findChild(QProgressBar, "notificationToastProgress") is not None
    toast.close()
    qapp.processEvents()


def test_notification_toast_close_button_dismisses_toast(qapp) -> None:
    toast = NotificationToast("Title", "Body", severity="info", duration_ms=0)
    closed: list[bool] = []
    toast.closed.connect(lambda: closed.append(True))
    toast.show()
    qapp.processEvents()
    close_button = toast.findChild(QPushButton, "notificationToastClose")
    assert close_button is not None
    close_button.click()
    qapp.processEvents()
    assert closed


def test_toast_manager_caps_visible_toasts_at_four(qapp) -> None:
    manager = ToastManager()
    for idx in range(5):
        manager.show_toast(f"Title {idx}", "Body", severity="info", duration_ms=0)
        qapp.processEvents()
    assert len(manager._toasts) <= 4  # noqa: SLF001 - UI contract assertion
    for toast in list(manager._toasts):  # noqa: SLF001 - UI contract assertion
        toast.close()
    qapp.processEvents()
