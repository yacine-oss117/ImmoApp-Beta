"""
Shared helpers for splash screens.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTreeView, QWidget

logger = logging.getLogger(__name__)

WARM_TABS = ("Match", "Clients", "Listings", "CRM")

if TYPE_CHECKING:
    from app.main_window_tabs_types import TabHostProtocol


def _resolve_tab_widget(widget: QWidget) -> QWidget:
    """Return the real tab content when a container wrapper is used."""
    layout = widget.layout()
    if layout is None:
        return widget
    if layout.count() != 1:
        return widget
    item = layout.itemAt(0)
    child = item.widget() if item is not None else None
    return child if isinstance(child, QWidget) else widget


def warm_tab_data(main_window: TabHostProtocol | None, title: str) -> None:
    """Warm tab data to avoid first-switch stalls."""
    if not main_window:
        return
    try:
        if title == "Clients" and main_window.clients_tab is not None:
            client_model = main_window.clients_tab._model
            if client_model.rowCount() > 0:
                idx = client_model.index(0, 0)
                if idx.isValid():
                    client_model.data(idx, int(Qt.ItemDataRole.DisplayRole))
        elif title == "Listings" and main_window.listings_tab is not None:
            listing_model = main_window.listings_tab._model
            if listing_model.rowCount() > 0:
                idx = listing_model.index(0, 0)
                if idx.isValid():
                    listing_model.data(idx, int(Qt.ItemDataRole.DisplayRole))
        elif title == "Match" and main_window.match_tab is not None:
            main_window.match_tab._load_counts_from_cache_or_compute()
        elif title == "CRM" and main_window.crm_tab is not None:
            main_window.crm_tab.refresh()
    except Exception:
        logger.warning("Warm tab %s failed", title, exc_info=True)


def prewarm_tab_layout(
    main_window: TabHostProtocol | None, title: str, fallback_index: int
) -> None:
    """Force Qt to lay out a tab once while splash is visible."""
    if not main_window:
        return
    tabs = getattr(main_window, "tabs", None)
    if tabs is None:
        return
    try:
        target_index = -1
        for tab_idx in range(tabs.count()):
            data = tabs.tabBar().tabData(tab_idx)
            tab_id = data if isinstance(data, str) else tabs.tabText(tab_idx)
            if tab_id == title:
                target_index = tab_idx
                break
        if target_index < 0:
            return
        prev_index = tabs.currentIndex()
        tabs.setCurrentIndex(target_index)
        QApplication.processEvents()
        tabs.setCurrentIndex(fallback_index if fallback_index >= 0 else prev_index)
        QApplication.processEvents()
    except Exception:
        logger.warning("Prewarm layout for %s failed", title, exc_info=True)


def prewarm_tab_heavy(
    main_window: TabHostProtocol | None,
    title: str,
    fallback_index: int,
    rows: int = 25,
    cols: int = 6,
) -> None:
    """Force heavier layout/model work while splash is visible."""
    if not main_window:
        return
    tabs = getattr(main_window, "tabs", None)
    if tabs is None:
        return
    try:
        target_index = -1
        for idx in range(tabs.count()):
            data = tabs.tabBar().tabData(idx)
            tab_id = data if isinstance(data, str) else tabs.tabText(idx)
            if tab_id == title:
                target_index = idx
                break
        if target_index < 0:
            return

        prev_index = tabs.currentIndex()
        tabs.setCurrentIndex(target_index)
        QApplication.processEvents()

        current = tabs.currentWidget()
        if isinstance(current, QWidget):
            content = _resolve_tab_widget(current)
            tree = getattr(content, "tree", None)
            if isinstance(tree, QTreeView):
                model = tree.model()
                if model is not None:
                    row_count = min(rows, model.rowCount())
                    col_count = min(cols, model.columnCount())
                    for r in range(row_count):
                        for c in range(col_count):
                            model_index = model.index(r, c)
                            if model_index.isValid():
                                model.data(model_index, int(Qt.ItemDataRole.DisplayRole))
                    tree.doItemsLayout()
                    tree.viewport().update()
                    tree.setUpdatesEnabled(False)
                    tree.setUpdatesEnabled(True)
                tree.setSizeAdjustPolicy(QAbstractItemView.SizeAdjustPolicy.AdjustToContents)
                QApplication.processEvents()

        tabs.setCurrentIndex(fallback_index if fallback_index >= 0 else prev_index)
        QApplication.processEvents()
    except Exception:
        logger.warning("Heavy prewarm for %s failed", title, exc_info=True)
