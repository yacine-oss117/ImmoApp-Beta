"""
Tree expand/collapse controller for SQL-backed QTreeView tables.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Protocol

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QTimer
from PySide6.QtWidgets import QPushButton, QTreeView

_ROOT_PARENT = QModelIndex()


class _RootRowModel(Protocol):
    """Protocol for models that expose cached root rows for expansion."""

    def loaded_root_rows(self) -> Iterable[int]:
        """Return currently cached root row indices."""

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = _ROOT_PARENT,
    ) -> QModelIndex:
        """Return model index for a row/column."""


class TreeExpandController(QObject):
    """Queue-based expand/collapse controller to avoid UI stalls."""

    def __init__(
        self,
        tree: QTreeView,
        model: _RootRowModel,
        *,
        expanded_label: str,
        collapsed_label: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._tree = tree
        self._model = model
        self._expanded_label = expanded_label
        self._collapsed_label = collapsed_label
        self._button: QPushButton | None = None

        self._all_expanded = False
        self._expand_queue: deque[QPersistentModelIndex] = deque()
        self._expand_target = False

        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._process_expand_queue)

    @property
    def all_expanded(self) -> bool:
        """Return whether the controller considers the tree expanded."""
        return self._all_expanded

    def bind_button(self, button: QPushButton) -> None:
        """Bind the expand/collapse button to this controller."""
        self._button = button
        self._button.setText(self._collapsed_label)

    def toggle_expand_all(self) -> None:
        """Toggle expand/collapse for loaded rows."""
        self.set_all_expanded(not self._all_expanded)

    def set_all_expanded(self, expand: bool) -> None:
        """Set expansion state for loaded rows and update button."""
        self._all_expanded = expand
        if self._button:
            self._button.setText(self._expanded_label if expand else self._collapsed_label)
        self.queue_expand_all(expand)

    def set_loaded_expanded(self, expand: bool) -> None:
        """Expand/collapse only currently loaded root rows."""
        for row in list(self._model.loaded_root_rows()):
            index = self._model.index(row, 0, _ROOT_PARENT)
            if not index.isValid():
                continue
            if expand:
                self._tree.expand(index)
            else:
                self._tree.collapse(index)

    def queue_expand_all(self, expand: bool) -> None:
        """Queue expansion/collapse to avoid blocking the UI."""
        if self._timer.isActive():
            self._timer.stop()
        self._expand_target = expand
        self._expand_queue.clear()
        for row in sorted(self._model.loaded_root_rows()):
            index = self._model.index(row, 0, _ROOT_PARENT)
            if index.isValid():
                self._expand_queue.append(QPersistentModelIndex(index))
        if not self._expand_queue:
            return
        self._timer.start()

    def cancel_pending(self) -> None:
        """Cancel any queued expand/collapse work."""
        if self._timer.isActive():
            self._timer.stop()
        self._expand_queue.clear()

    def reapply_after_layout_change(self) -> None:
        """Reapply expansion after sorting or layout changes."""
        if self._all_expanded:
            self.queue_expand_all(True)

    def _process_expand_queue(self) -> None:
        batch_size = 50
        for _ in range(min(batch_size, len(self._expand_queue))):
            index = self._expand_queue.popleft()
            if not index.isValid():
                continue
            try:
                if self._expand_target:
                    self._tree.expand(index)
                else:
                    self._tree.collapse(index)
            except RuntimeError:
                self.cancel_pending()
                return
        if not self._expand_queue:
            self._timer.stop()
