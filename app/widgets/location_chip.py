"""
Location chip widget.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from app.utils.i18n import tr_factory

_TR = tr_factory("LocationChip")


class LocationChip(QFrame):
    """Single location chip with remove button."""

    removed = Signal(str)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self.setObjectName("locationChip")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 6, 2)
        layout.setSpacing(6)

        label = QLabel(text, self)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        remove_btn = QToolButton(self)
        remove_btn.setText("x")
        remove_btn.setToolTip(_TR("Remove"))
        remove_btn.setAccessibleName(_TR("Remove location"))
        remove_btn.clicked.connect(self._emit_removed)

        layout.addWidget(label)
        layout.addWidget(remove_btn)

    def _emit_removed(self) -> None:
        self.removed.emit(self._text)
