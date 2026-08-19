"""Session lifecycle helpers for the main window."""

from __future__ import annotations

from typing import Protocol, cast

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from app.services.api_client import (
    clear_persisted_session,
    clear_session_credentials,
    reset_api_session,
)
from app.services.api_config import clear_api_token
from app.utils.i18n import tr_factory

_TR = tr_factory("MainWindowSession")


class _SessionHost(Protocol):
    def close(self) -> None: ...
    def hide(self) -> None: ...


class MainWindowSessionMixin:
    """Mixin handling disconnect/re-auth flows."""

    def _disconnect_session(self: _SessionHost) -> None:
        parent = cast(QWidget, getattr(self, "_host", self))
        result = QMessageBox.question(
            parent,
            _TR("Disconnect"),
            _TR("Disconnect from the server and return to the login screen?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        if hasattr(self, "_stop_notifications"):
            self._stop_notifications()

        clear_api_token()
        clear_persisted_session()
        clear_session_credentials()
        reset_api_session()

        app = QApplication.instance()
        if app is None:
            self.close()
            return
        if not isinstance(app, QApplication):
            self.close()
            return

        self.hide()

        from app.widgets.login_dialog import ensure_login

        if not ensure_login(cast(QApplication, app)):
            app.quit()
            return

        from app.widgets.splash_screen import startup_with_preload

        new_window = startup_with_preload(cast(QApplication, app))
        new_window.show()
        self.close()
