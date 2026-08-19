"""Shared QTreeView configuration helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTreeView

from app.constants import APP, ORG


def configure_tree(tree: QTreeView) -> None:
    """Configure standard tree behavior and styling."""
    tree.setProperty("immoTreeRole", "workspace")
    tree.setUniformRowHeights(True)
    tree.setAnimated(False)
    tree.setIndentation(20)
    tree.setRootIsDecorated(True)
    tree.setExpandsOnDoubleClick(True)
    tree.setAlternatingRowColors(True)
    tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tree.setSortingEnabled(True)
    tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    header = tree.header()
    header.setStretchLastSection(True)
    header.setSectionsClickable(True)
    header.setSortIndicatorShown(True)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setMinimumSectionSize(40)


def apply_column_widths(
    tree: QTreeView,
    settings_prefix: str,
    default_widths: Sequence[int],
) -> None:
    """Apply persisted column widths with provided defaults."""
    settings = QSettings(ORG, APP)
    for i, default_width in enumerate(default_widths):
        saved_raw = settings.value(f"{settings_prefix}/column_{i}_width", default_width, int)
        saved_width = int(cast(int, saved_raw) or default_width)
        tree.setColumnWidth(i, saved_width)
