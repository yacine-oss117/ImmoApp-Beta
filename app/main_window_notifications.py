"""Notifications hub wiring for the main window."""

from __future__ import annotations

import logging
from typing import Protocol, cast

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QStatusBar, QStyle, QToolButton, QWidget

from app.services.notification_severity import severity_for_event_type
from app.services.notifications_repository import fetch_unread_count
from app.utils.i18n import tr_factory
from app.widgets.notification_hub import NotificationHub
from app.widgets.notification_toast import ToastManager

logger = logging.getLogger(__name__)
_TR = tr_factory("MainWindowNotifications")


class _NotificationHost(Protocol):
    status_bar: QStatusBar
    _notifications: NotificationHub | None
    _toast_manager: ToastManager
    _notification_unread: int
    _notifications_button: QToolButton

    def style(self) -> QStyle: ...
    def _startup_light_enabled(self) -> bool: ...
    def _handle_notification(self, payload: dict[str, object]) -> None: ...
    def _refresh_notification_count(self) -> None: ...
    def _update_notification_badge(self) -> None: ...
    def _open_notifications(self) -> None: ...


class MainWindowNotificationsMixin:
    """Mixin providing notifications hub + inbox UI wiring."""

    _notifications: NotificationHub | None
    _toast_manager: ToastManager
    _notification_unread: int
    _notifications_button: QToolButton

    def _init_notifications(self: _NotificationHost, startup_light: bool) -> None:
        host_obj = cast(QObject, getattr(self, "_host", self))
        self._notifications = NotificationHub(host_obj)
        self._notifications.notification_received.connect(self._handle_notification)
        if not startup_light:
            self._notifications.start()
        self._toast_manager = ToastManager(host_obj)

    def _stop_notifications(self) -> None:
        if self._notifications is not None:
            self._notifications.stop()

    def _handle_notification(self: _NotificationHost, payload: dict[str, object]) -> None:
        logger.info("Notification received: %s", payload)
        title = str(payload.get("title") or _TR("Notification"))
        body = str(payload.get("body") or "")
        event_type = str(payload.get("type") or "")
        severity = severity_for_event_type(event_type)
        self._toast_manager.show_toast(title, body, severity=severity)
        self._notification_unread += 1
        self._update_notification_badge()

    def _init_notifications_inbox(self: _NotificationHost) -> None:
        self._notification_unread = 0
        parent = cast(QWidget, getattr(self, "_host", self))
        self._notifications_button = QToolButton(parent)
        self._notifications_button.setObjectName("immoNotificationsButton")
        self._notifications_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._notifications_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        )
        self._notifications_button.setToolTip(_TR("Notifications"))
        self._notifications_button.clicked.connect(self._open_notifications)
        self.status_bar.addPermanentWidget(self._notifications_button)
        self._refresh_notification_count()

    def _refresh_notification_count(self: _NotificationHost) -> None:
        if self._startup_light_enabled():
            self._notification_unread = 0
            self._update_notification_badge()
            return
        try:
            self._notification_unread = fetch_unread_count()
        except Exception:
            self._notification_unread = 0
        self._update_notification_badge()

    def _update_notification_badge(self: _NotificationHost) -> None:
        count = self._notification_unread
        label = _TR("Notifications")
        if count > 0:
            label = _TR("Notifications ({count})").format(count=count)
        self._notifications_button.setText(label)

    def _open_notifications(self: _NotificationHost) -> None:
        from app.views.dialogs.notifications_dialog import NotificationsDialog

        dialog = NotificationsDialog(cast(QWidget, getattr(self, "_host", self)))
        dialog.exec()
        self._notification_unread = dialog.latest_unread
        self._update_notification_badge()

    def _startup_light_enabled(self) -> bool:
        return bool(getattr(self, "_startup_light", False))
