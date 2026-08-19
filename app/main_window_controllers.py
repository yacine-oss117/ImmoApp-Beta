"""Composition controllers for MainWindow domains.

This module removes direct mixin inheritance from MainWindow while preserving
existing behavior and method names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.main_window_dialogs import MainWindowDialogsMixin
from app.main_window_menus import MainWindowMenuMixin
from app.main_window_notifications import MainWindowNotificationsMixin
from app.main_window_session import MainWindowSessionMixin
from app.main_window_status import MainWindowStatusMixin
from app.main_window_tabs import MainWindowTabMixin


class _DelegatingController:
    """Forward attribute access/state to the MainWindow host."""

    _host: Any

    def __init__(self, host: Any) -> None:
        object.__setattr__(self, "_host", host)

    def __getattr__(self, name: str) -> Any:
        # Delegate only missing attributes to the host.
        # This avoids interfering with QObject/PySide meta-object internals.
        host = object.__getattribute__(self, "_host")
        return getattr(host, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_host":
            object.__setattr__(self, name, value)
            return
        setattr(self._host, name, value)


class MainWindowStatusController(MainWindowStatusMixin, _DelegatingController):
    pass


class MainWindowTabController(MainWindowTabMixin, _DelegatingController):
    pass


class MainWindowDialogsController(MainWindowDialogsMixin, _DelegatingController):
    pass


class MainWindowMenuController(MainWindowMenuMixin, _DelegatingController):
    pass


class MainWindowSessionController(MainWindowSessionMixin, _DelegatingController):
    pass


class MainWindowNotificationsController(MainWindowNotificationsMixin, _DelegatingController):
    pass


@dataclass(frozen=True)
class MainWindowControllers:
    status: MainWindowStatusController
    tabs: MainWindowTabController
    dialogs: MainWindowDialogsController
    menus: MainWindowMenuController
    session: MainWindowSessionController
    notifications: MainWindowNotificationsController

    @classmethod
    def build(cls, host: Any) -> MainWindowControllers:
        return cls(
            status=MainWindowStatusController(host),
            tabs=MainWindowTabController(host),
            dialogs=MainWindowDialogsController(host),
            menus=MainWindowMenuController(host),
            session=MainWindowSessionController(host),
            notifications=MainWindowNotificationsController(host),
        )

    def iter_all(self) -> tuple[object, ...]:
        return (
            self.status,
            self.tabs,
            self.dialogs,
            self.menus,
            self.session,
            self.notifications,
        )
