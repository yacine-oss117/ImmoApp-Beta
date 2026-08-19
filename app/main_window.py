"""Main application window and tab wiring."""

import os

from PySide6.QtCore import QSettings, QThreadPool, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from app.constants import APP, ORG
from app.main_window_controllers import MainWindowControllers
from app.services.db_core import db_init
from app.ui.theme_manager import apply_theme, current_density, current_theme, set_density
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_blocking
from app.utils.settings_schema import apply_settings_schema

_TR = tr_factory("MainWindow")
_STARTUP_LIGHT = os.environ.get("IMMOAPP_STARTUP_LIGHT") == "1"


class MainWindow(QMainWindow):
    """The central window of the application, coordinating tabs and menus."""

    status_message = Signal(str, int)
    tz_refresh_result = Signal(object, float)

    def __init__(self) -> None:
        super().__init__()
        self._startup_light = _STARTUP_LIGHT
        self._controllers = MainWindowControllers.build(self)
        self.setWindowTitle(_TR("Yacine Real Estate Matcher"))
        self.setObjectName("immoMainWindow")

        # Restore window geometry from settings
        settings = QSettings(ORG, APP)
        apply_settings_schema(settings)
        geometry = settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            # Default size if no saved geometry
            self.resize(1200, 800)

        self.setMinimumSize(1000, 600)  # Prevent layout issues

        # Constrain background QRunnable usage to avoid oversubscription.
        pool = QThreadPool.globalInstance()
        raw_desired = settings.value("ui/max_threadpool", 4, int)
        cpu_count = os.cpu_count() or 4
        desired = int(raw_desired) if isinstance(raw_desired, (int, float, str)) else 4
        max_threads = max(2, min(desired, cpu_count))
        pool.setMaxThreadCount(max_threads)

        # Initialize API connectivity (off UI thread)
        if not _STARTUP_LIGHT:
            run_blocking(db_init, timeout_ms=20000)

        # Apply persisted theme at runtime (main.py already applies globally).
        app_instance = QApplication.instance()
        if isinstance(app_instance, QApplication):
            apply_theme(app_instance)

        self._controllers.menus._init_menus()
        self._controllers.notifications._init_notifications(_STARTUP_LIGHT)

        if _STARTUP_LIGHT:
            placeholder = QWidget(self)
            self.setCentralWidget(placeholder)
            return

        self._controllers.tabs._init_tabs()
        self._controllers.status._init_status_bar()
        self._controllers.notifications._init_notifications_inbox()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Save window geometry before closing."""
        self._controllers.notifications._stop_notifications()
        settings = QSettings(ORG, APP)
        settings.setValue("window/geometry", self.saveGeometry())
        event.accept()

    # --- Explicit cross-controller bridges (strict boundaries, no dynamic fallback) ---
    def _disconnect_session(self) -> None:
        self._controllers.session._disconnect_session()

    def _stop_notifications(self) -> None:
        self._controllers.notifications._stop_notifications()

    def _open_notifications(self) -> None:
        self._controllers.notifications._open_notifications()

    def _kickoff_tz_refresh_async(self, force: bool = False) -> None:
        self._controllers.status._kickoff_tz_refresh_async(force=force)

    def _update_status_bar(self) -> None:
        self._controllers.status._update_status_bar()

    def _refresh_all_tabs(self) -> None:
        self._controllers.tabs._refresh_all_tabs()

    def _backup_database_manual(self) -> None:
        self._controllers.dialogs._backup_database_manual()

    def _open_time_settings(self) -> None:
        self._controllers.dialogs._open_time_settings()

    def _open_wa_templates(self) -> None:
        self._controllers.dialogs._open_wa_templates()

    def _open_agency_settings(self) -> None:
        self._controllers.dialogs._open_agency_settings()

    def _open_user_management(self) -> None:
        self._controllers.dialogs._open_user_management()

    def _open_security_settings(self) -> None:
        self._controllers.dialogs._open_security_settings()

    def _open_session_manager(self) -> None:
        self._controllers.dialogs._open_session_manager()

    def _open_contract_builder(self) -> None:
        self._controllers.dialogs._open_contract_builder()

    def _open_communes_manager(self) -> None:
        self._controllers.dialogs._open_communes_manager()

    def _open_trash_dialog(self) -> None:
        self._controllers.dialogs._open_trash_dialog()

    def _open_audit_logs(self) -> None:
        self._controllers.dialogs._open_audit_logs()

    def _open_storage_delete(self) -> None:
        self._controllers.dialogs._open_storage_delete()

    def _open_health_dialog(self) -> None:
        self._controllers.dialogs._open_health_dialog()

    def _open_sync_issues(self) -> None:
        self._controllers.dialogs._open_sync_issues()

    def _open_send_diagnostics(self) -> None:
        self._controllers.dialogs._open_send_diagnostics()

    def _open_support_bundle(self) -> None:
        self._controllers.dialogs._open_support_bundle()

    def _open_welcome_guide(self) -> None:
        self._controllers.dialogs._open_welcome_guide()

    def _open_security_controls(self) -> None:
        self._controllers.dialogs._open_security_controls()

    def _set_theme(self, theme_name: str, _checked: bool = False) -> None:
        app_instance = QApplication.instance()
        if isinstance(app_instance, QApplication):
            apply_theme(app_instance, theme_name, persist=True)

    def _current_theme(self) -> str:
        return current_theme()

    def _set_density(self, density_name: str, _checked: bool = False) -> None:
        app_instance = QApplication.instance()
        selected = set_density(density_name)
        if isinstance(app_instance, QApplication):
            apply_theme(app_instance, self._current_theme(), selected, persist=False)

    def _current_density(self) -> str:
        return current_density()
