"""
Helper functions for MainWindow tab management.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from app.main_window_tabs_types import SwapTrackableProtocol, TabHostProtocol
from app.utils.i18n import tr_factory
from app.widgets.splash_shared import prewarm_tab_heavy, prewarm_tab_layout, warm_tab_data

_TR = tr_factory("MainWindowTabs")
logger = logging.getLogger(__name__)


def tab_id_for_index(host: TabHostProtocol, index: int) -> str:
    data = host.tabs.tabBar().tabData(index)
    if isinstance(data, str):
        return data
    return str(host.tabs.tabText(index))


def ensure_tab_loaded(host: TabHostProtocol, index: int) -> None:
    tab_id = tab_id_for_index(host, index)
    if tab_id in host._tab_load_in_progress:
        return
    if tab_id in host._loaded_tabs:
        return
    factory = host._tab_factories.get(tab_id)
    if not factory:
        return
    host._tab_load_in_progress.add(tab_id)
    try:
        start = time.perf_counter()
        widget = factory()
        create_ms = (time.perf_counter() - start) * 1000.0

        widget.hide()

        host._loaded_tabs[tab_id] = widget
        container = QWidget(host.tabs)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(widget)
        host._tab_containers[tab_id] = container

        insert_index = max(0, min(index, host.tabs.count()))
        host.tabs.insertTab(insert_index, container, host._tab_label(tab_id))
        host.tabs.tabBar().setTabData(insert_index, tab_id)
        widget.show()

        total_ms = (time.perf_counter() - start) * 1000.0
        if total_ms >= 50:
            logger.info(
                "Tab load: %s create %.1fms total %.1fms",
                tab_id,
                create_ms,
                total_ms,
            )
    finally:
        host._tab_load_in_progress.discard(tab_id)


def schedule_post_startup_prewarm(host: TabHostProtocol, warm_tabs: tuple[str, ...]) -> None:
    """Warm tab layout/data after the event loop starts to avoid splash-time crashes."""
    if host._post_startup_prewarm_scheduled:
        return
    host._post_startup_prewarm_scheduled = True

    def _run() -> None:
        host._prewarm_running = True
        host.tabs.blockSignals(True)
        try:
            for title in warm_tabs:
                for idx in range(host.tabs.count()):
                    if tab_id_for_index(host, idx) == title:
                        ensure_tab_loaded(host, idx)
                        break
                prewarm_tab_layout(host, title, fallback_index=0)
                if title == "Clients":
                    prewarm_tab_heavy(host, title, fallback_index=0, rows=100, cols=8)
                else:
                    prewarm_tab_heavy(host, title, fallback_index=0)
                warm_tab_data(host, title)
        finally:
            host.tabs.blockSignals(False)
            host._prewarm_running = False

    QTimer.singleShot(0, _run)


def preload_all_tabs(
    host: TabHostProtocol,
    tab_ids: tuple[str, ...],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> None:
    """Preload all tabs during startup to eliminate jitter on first click."""
    total = len(tab_ids) - 1
    progress = 0
    for tab_id in tab_ids[1:]:
        if progress_callback:
            progress_callback(progress, total, _TR("Loading {tab} tab...").format(tab=tab_id))

        for idx in range(host.tabs.count()):
            if tab_id_for_index(host, idx) == tab_id:
                ensure_tab_loaded(host, idx)
                break
        progress += 1

    host.tabs.blockSignals(True)
    host.tabs.setCurrentIndex(0)
    host.tabs.blockSignals(False)

    if progress_callback:
        progress_callback(total, total, _TR("Ready!"))


def refresh_all_tabs(host: TabHostProtocol) -> None:
    """Refresh all loaded tabs."""
    if host.clients_tab is not None:
        host.clients_tab.refresh_table()
    if host.listings_tab is not None:
        host.listings_tab.refresh_table()
    if host.match_tab is not None:
        if hasattr(host.match_tab, "reset_view"):
            host.match_tab.reset_view()
        else:
            host.match_tab.mark_all_dirty()
    host.dashboard_tab.refresh_stats()
    if host.crm_tab is not None:
        host.crm_tab.refresh()


def prepare_for_db_swap(host: TabHostProtocol) -> bool:
    """Stop background workers before swapping the active database."""
    parent_widget = cast(QWidget, host)
    stopped = True
    if host.match_tab is not None:
        try:
            stopped = bool(host.match_tab.stop_background_workers())
        except (AttributeError, RuntimeError):
            logger.error("Failed to stop match workers before DB swap", exc_info=True)
            stopped = False

    if not stopped:
        if hasattr(host, "status_bar"):
            host.status_bar.showMessage(_TR("Database swap delayed: workers still running"), 5000)
        QMessageBox.warning(
            parent_widget,
            _TR("Database Swap Delayed"),
            _TR("Background workers are still running. Please wait a moment and retry."),
        )
        return False

    from app.services.db_core import wait_for_no_active_connections

    if not wait_for_no_active_connections():
        if hasattr(host, "status_bar"):
            host.status_bar.showMessage(
                _TR("Database swap delayed: active connections still open"), 5000
            )
        QMessageBox.warning(
            parent_widget,
            _TR("Database Swap Delayed"),
            _TR("Active database connections are still open. Please retry in a moment."),
        )
        return False

    return True


def navigate_to_match(host: TabHostProtocol, client_id: int) -> None:
    """Navigate to Match tab and select a specific client."""
    match_idx = -1
    for i in range(host.tabs.count()):
        if tab_id_for_index(host, i) == "Match":
            match_idx = i
            break

    if match_idx != -1:
        ensure_tab_loaded(host, match_idx)
        host.tabs.setCurrentIndex(match_idx)

        if host.match_tab is not None:
            host.match_tab.select_client(client_id)


def track_first_paint(host: TabHostProtocol, index: int) -> None:
    tab_id = tab_id_for_index(host, index)
    widget = host._loaded_tabs.get(tab_id)
    if widget is not None:
        first_paint_logged = getattr(widget, "_first_paint_logged", None)
        if isinstance(first_paint_logged, bool) and not first_paint_logged:
            swap_widget = cast(SwapTrackableProtocol, widget)
            swap_widget._swap_started_at = time.perf_counter()
