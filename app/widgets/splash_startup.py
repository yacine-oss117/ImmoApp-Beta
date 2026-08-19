"""
Startup splash screen and preload orchestration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QProgressBar, QVBoxLayout, QWidget

from app.services.db_core import db_init
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_blocking
from app.widgets.splash_shared import prewarm_tab_heavy, prewarm_tab_layout, warm_tab_data

logger = logging.getLogger(__name__)
_TR = tr_factory("StartupSplash")

if TYPE_CHECKING:
    from app.main_window import MainWindow


class StartupSplash(QDialog):
    """
    Unified startup splash that handles:
    1. Cache building (if needed)
    2. Tab preloading (always)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_TR("Yacine Real Estate Matcher"))
        self.setFixedSize(450, 220)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setObjectName("immoStartupSplash")

        self._setup_ui()
        self._main_window: MainWindow | None = None

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(_TR("Yacine Real Estate Matcher"))
        title.setObjectName("startupTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont("Segoe UI", 18, QFont.Weight.Bold)
        title.setFont(title_font)
        layout.addWidget(title)

        self._status = QLabel(_TR("Loading your data..."))
        self._status.setObjectName("startupStatus")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setObjectName("startupProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

        self._detail = QLabel("")
        self._detail.setObjectName("startupDetail")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._detail)

    def run_startup(self) -> MainWindow:
        """
        Run the complete startup sequence and return the ready MainWindow.
        """
        from app.main_window import MainWindow

        self.show()
        QApplication.processEvents()

        self._update_progress(0, _TR("Connecting..."), "")
        run_blocking(db_init, timeout_ms=20000)
        try:
            from app.services.user_context import sync_user_context_async

            sync_user_context_async()
        except Exception:
            logger.warning("User context sync failed", exc_info=True)
        self._update_progress(40, _TR("Loading your dashboard..."), "")
        try:
            from app.services.dashboard_cache import refresh_dashboard_stats

            run_blocking(refresh_dashboard_stats, timeout_ms=20000)
        except Exception:
            self._update_progress(
                44,
                _TR("Dashboard data unavailable"),
                _TR("Continuing with limited data for now."),
            )
            logger.error("Failed to refresh dashboard stats", exc_info=True)
            try:
                from app.services.dashboard_cache import reset_dashboard_cache

                reset_dashboard_cache()
            except Exception:
                logger.warning("Failed to reset dashboard cache after error", exc_info=True)

        self._update_progress(50, _TR("Almost ready..."), "")
        self._main_window = MainWindow()
        tabs_controller = self._main_window._controllers.tabs

        tabs_controller.tabs.blockSignals(True)
        tabs_controller.tabs.setCurrentIndex(0)
        tabs_controller.tabs.blockSignals(False)

        self._update_progress(90, _TR("Preparing screens..."), "")
        QApplication.processEvents()

        if tabs_controller.listings_tab is not None:
            try:
                tabs_controller.listings_tab.prime_data()
            except Exception:
                logger.warning("Listings prime_data failed during startup", exc_info=True)
        for title in ("Match", "Clients", "Listings", "CRM"):
            try:
                prewarm_tab_layout(tabs_controller, title, fallback_index=0)
                if title == "Clients":
                    prewarm_tab_heavy(tabs_controller, title, fallback_index=0, rows=100, cols=8)
                else:
                    prewarm_tab_heavy(tabs_controller, title, fallback_index=0)
                warm_tab_data(tabs_controller, title)
            except Exception:
                logger.warning("Startup warmup failed for %s tab", title, exc_info=True)

        self._update_progress(100, _TR("Ready!"), "")
        QApplication.processEvents()

        if self._main_window is None:
            raise RuntimeError("Startup failed to initialize main window.")
        return self._main_window

    def _update_progress(self, percent: int, status: str, detail: str) -> None:
        """Update progress display."""
        self._progress.setValue(percent)
        self._status.setText(status)
        self._detail.setText(detail)
        QApplication.processEvents()


def startup_with_preload(app: QApplication) -> MainWindow:
    """
    Complete startup with unified splash screen.
    """
    splash = StartupSplash()
    win = splash.run_startup()
    splash.close()
    return win
