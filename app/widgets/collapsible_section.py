"""
Collapsible Section Widget - Expandable/collapsible panel with header.

Usage:
    section = CollapsibleSection("Client Info", parent)
    section.set_content(my_form_widget)
    section.collapsed_changed.connect(on_collapse)

Features:
    - Click header to expand/collapse
    - Animated arrow indicator
    - Optional delete button
    - Emits signals for state changes
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.utils.i18n import tr_factory
from app.utils.text_safety import set_label_plain_text, set_label_rich_text

_TR = tr_factory("CollapsibleSection")


class _HeaderFrame(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        self.clicked.emit()


class CollapsibleSection(QWidget):
    """
    A collapsible section with a clickable header and content area.
    """

    # Signals
    collapsed_changed = Signal(bool)  # Emits True when collapsed, False when expanded
    delete_requested = Signal()  # Emits when delete button clicked

    def __init__(
        self,
        title: str = "",
        parent: QWidget | None = None,
        show_delete: bool = False,
        collapsible: bool = True,
    ) -> None:
        super().__init__(parent)
        self._is_collapsed = False
        self._title = title
        self._show_delete = show_delete
        self._collapsible = collapsible
        self._content_widget: QWidget | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header frame
        self._header = _HeaderFrame(self)
        self._header.setFrameShape(QFrame.Shape.StyledPanel)
        self._header.setCursor(
            Qt.CursorShape.PointingHandCursor if self._collapsible else Qt.CursorShape.ArrowCursor
        )
        self._header.setObjectName("collapsibleHeader")

        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(8)

        # Arrow indicator
        self._arrow = QLabel("v")
        self._arrow.setFixedWidth(16)
        self._arrow.setObjectName("collapsibleArrow")
        self._arrow.setVisible(self._collapsible)
        header_layout.addWidget(self._arrow)

        # Title
        self._title_label = QLabel()
        self._title_label.setObjectName("collapsibleTitle")
        set_label_plain_text(self._title_label, self._title)
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        # Delete button (optional)
        if self._show_delete:
            self._delete_btn = QPushButton("X")
            self._delete_btn.setObjectName("collapsibleDeleteButton")
            self._delete_btn.setFixedSize(24, 24)
            self._delete_btn.setToolTip(_TR("Delete"))
            self._delete_btn.setAccessibleName(_TR("Delete section"))
            self._delete_btn.setProperty("immoVariant", "danger")
            self._delete_btn.clicked.connect(self._on_delete_clicked)
            header_layout.addWidget(self._delete_btn)

        # Content container
        self._content_container = QFrame()
        self._content_container.setFrameShape(QFrame.Shape.NoFrame)
        self._content_layout = QVBoxLayout(self._content_container)
        self._content_layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(self._header)
        layout.addWidget(self._content_container)

        # Click handler
        self._header.clicked.connect(self._header_clicked)
        if not self._collapsible:
            self._content_container.setVisible(True)

    def _header_clicked(self) -> None:
        """Toggle collapsed state when header is clicked."""
        if not self._collapsible:
            return
        self.set_collapsed(not self._is_collapsed)

    def _on_delete_clicked(self) -> None:
        """Emit delete signal."""
        self.delete_requested.emit()

    def set_collapsed(self, collapsed: bool) -> None:
        """Explicitly set the visibility of the content area."""
        if not self._collapsible:
            self._is_collapsed = False
            self._content_container.setVisible(True)
            self._arrow.setText("v")
            return
        self._is_collapsed = collapsed
        self._content_container.setVisible(not collapsed)
        self._arrow.setText(">" if collapsed else "v")
        self.collapsed_changed.emit(collapsed)

    def is_collapsed(self) -> bool:
        """Return True if the content area is currently hidden."""
        return self._is_collapsed

    def is_collapsible(self) -> bool:
        """Return True when the section supports collapse/expand interaction."""
        return self._collapsible

    def set_title(self, title: str) -> None:
        """Update the text displayed in the section header."""
        self._title = title
        set_label_plain_text(self._title_label, title)

    def set_delete_button_object_name(self, object_name: str) -> None:
        """Set a stable object name on the optional delete button."""
        delete_btn = getattr(self, "_delete_btn", None)
        if delete_btn is not None:
            delete_btn.setObjectName(object_name)

    def set_trusted_title_html(self, html_title: str) -> None:
        """Update the header using trusted rich text (already escaped)."""
        self._title = html_title
        set_label_rich_text(self._title_label, html_title)

    def title(self) -> str:
        """Return the current header text."""
        return self._title

    def set_content(self, widget: QWidget) -> None:
        """Embed a widget into the collapsible content area."""
        # Remove old content if any
        if self._content_widget:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)

        self._content_widget = widget
        self._content_layout.addWidget(widget)

    def content(self) -> QWidget | None:
        """Return the currently embedded content widget."""
        return self._content_widget

    def collapse(self) -> None:
        """Hide the content area."""
        self.set_collapsed(True)

    def expand(self) -> None:
        """Show the content area."""
        self.set_collapsed(False)

    def toggle(self) -> None:
        """Switch between expanded and collapsed states."""
        self.set_collapsed(not self._is_collapsed)

    def set_expanded(self, expanded: bool) -> None:
        """Set the expanded state (convenience method)."""
        self.set_collapsed(not expanded)
