"""
Action Delegate for QTreeView - Painted Buttons (No Widgets)

This delegate paints Edit/Delete buttons directly onto the view
instead of creating actual QPushButton widgets, enabling 60fps performance.
"""

from functools import lru_cache
from typing import Protocol, cast

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from app.ui.theme_manager import current_theme
from app.ui.theme_tokens import get_theme_tokens


class _HasRect(Protocol):
    rect: QRect


@lru_cache(maxsize=2)
def _palette_for_theme(theme_name: str) -> dict[str, QColor]:
    tokens = get_theme_tokens(theme_name)
    return {
        "edit_bg": QColor(tokens["SURFACE_ALT"]),
        "edit_text": QColor(tokens["WARNING"]),
        "edit_hover": QColor(tokens["SURFACE_SOFT"]),
        "delete_bg": QColor(tokens["SURFACE_ALT"]),
        "delete_text": QColor(tokens["DANGER"]),
        "delete_hover": QColor(tokens["SURFACE_SOFT"]),
    }


def _current_palette() -> dict[str, QColor]:
    return _palette_for_theme(current_theme())


class ActionDelegate(QStyledItemDelegate):
    """
    Delegate that paints Edit/Delete buttons directly.

    Handles click detection via editorEvent to trigger actions.
    """

    # Signals for button clicks
    editClicked = Signal(QModelIndex)
    deleteClicked = Signal(QModelIndex)

    # Button dimensions (15% bigger)
    BUTTON_WIDTH = 58  # was 50
    BUTTON_HEIGHT = 28  # was 24
    BUTTON_SPACING = 6
    BUTTON_MARGIN = 4

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pressed_button: str | None = None
        self._pressed_index: QModelIndex | QPersistentModelIndex | None = None

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Paint the Edit and Delete buttons."""
        painter.save()

        # Get node type from model
        node_type = index.data(int(Qt.ItemDataRole.UserRole) + 2)  # ROLE_NODE_TYPE

        # Support both clients (client/demande) and listings (listing/offer)
        if node_type not in ("client", "demande", "listing", "offer"):
            painter.restore()
            return

        rect = cast(_HasRect, option).rect

        # Calculate button positions
        edit_rect = QRect(
            rect.x() + self.BUTTON_MARGIN,
            rect.y() + (rect.height() - self.BUTTON_HEIGHT) // 2,
            self.BUTTON_WIDTH,
            self.BUTTON_HEIGHT,
        )

        delete_rect = QRect(
            edit_rect.right() + self.BUTTON_SPACING,
            rect.y() + (rect.height() - self.BUTTON_HEIGHT) // 2,
            self.BUTTON_WIDTH + 10,
            self.BUTTON_HEIGHT,
        )
        palette = _current_palette()

        # Draw Edit button (grey bg, amber text)
        is_edit_pressed = self._pressed_button == "edit" and self._pressed_index == index
        self._draw_button(
            painter,
            edit_rect,
            "Edit",
            palette["edit_hover"] if is_edit_pressed else palette["edit_bg"],
            palette["edit_text"],
        )

        # Draw Delete button (grey bg, red text)
        is_del_pressed = self._pressed_button == "delete" and self._pressed_index == index
        self._draw_button(
            painter,
            delete_rect,
            "Delete",
            palette["delete_hover"] if is_del_pressed else palette["delete_bg"],
            palette["delete_text"],
        )

        painter.restore()

    def _draw_button(
        self, painter: QPainter, rect: QRect, text: str, bg_color: QColor, text_color: QColor
    ) -> None:
        """Draw a single button with grey bg and colored text."""
        # Draw rounded rectangle background
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect, 4, 4)

        # Draw colored text
        painter.setPen(QPen(text_color))
        font = painter.font()
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        """Handle mouse clicks on buttons."""
        if event.type() not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            return False

        if not isinstance(event, QMouseEvent):
            return False

        node_type = index.data(int(Qt.ItemDataRole.UserRole) + 2)
        # Support both clients (client/demande) and listings (listing/offer)
        if node_type not in ("client", "demande", "listing", "offer"):
            return False

        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        rect = cast(_HasRect, option).rect

        # Calculate button rects
        edit_rect = QRect(
            rect.x() + self.BUTTON_MARGIN,
            rect.y() + (rect.height() - self.BUTTON_HEIGHT) // 2,
            self.BUTTON_WIDTH,
            self.BUTTON_HEIGHT,
        )

        delete_rect = QRect(
            edit_rect.right() + self.BUTTON_SPACING,
            rect.y() + (rect.height() - self.BUTTON_HEIGHT) // 2,
            self.BUTTON_WIDTH + 10,
            self.BUTTON_HEIGHT,
        )

        if event.type() == QEvent.Type.MouseButtonPress:
            if edit_rect.contains(pos):
                self._pressed_button = "edit"
                self._pressed_index = index
                return True
            elif delete_rect.contains(pos):
                self._pressed_button = "delete"
                self._pressed_index = index
                return True

        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self._pressed_button and self._pressed_index == index:
                button = self._pressed_button
                pressed_index = self._pressed_index
                self._pressed_button = None
                self._pressed_index = None

                # Emit appropriate signal
                if button == "edit":
                    self.editClicked.emit(pressed_index)
                elif button == "delete":
                    self.deleteClicked.emit(pressed_index)
                return True

        return False

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """Return size hint for the actions column."""
        return QSize(self.BUTTON_MARGIN * 2 + self.BUTTON_WIDTH * 2 + self.BUTTON_SPACING + 10, 40)
