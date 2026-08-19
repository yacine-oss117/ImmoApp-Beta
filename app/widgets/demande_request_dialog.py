"""Modal editor for a client's property request."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models import Demande
from app.utils.i18n import tr_factory
from app.widgets.demande_form import DemandeForm

_TR = tr_factory("DemandeRequestDialog")


class DemandeRequestDialog(QDialog):
    """Create/edit dialog that keeps the large request form out of the Clients page."""

    def __init__(
        self,
        data: Mapping[str, object] | Demande | None = None,
        *,
        title: str | None = None,
        save_text: str | None = None,
        save_object_name: str = "demandeRequestSaveButton",
        cancel_object_name: str = "demandeRequestCancelButton",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial_data = data
        self._title = title or _TR("New Property Request")
        self._save_text = save_text or _TR("Add Request")
        self._save_object_name = save_object_name
        self._cancel_object_name = cancel_object_name
        self._setup_ui()
        if data is not None:
            self._form.set_data(data)

    def _setup_ui(self) -> None:
        self.setWindowTitle(self._title)
        self.setModal(True)
        self.setObjectName("immoDialog")
        self.setProperty("immoRole", "workspaceDialog")
        self.setAccessibleName(self._title)
        self.setMinimumSize(760, 540)
        self.resize(920, 690)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        title = QLabel(self._title, self)
        title.setObjectName("dialogSectionTitle")
        title.setProperty("immoDialogTitle", True)
        root.addWidget(title)

        scroll = QScrollArea(self)
        scroll.setObjectName("demandeRequestScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setProperty("immoRole", "editorScroll")
        scroll.setProperty("immoScrollRole", "compact")
        scroll.verticalScrollBar().setProperty("immoScrollRole", "compact")
        scroll.horizontalScrollBar().setProperty("immoScrollRole", "compact")

        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(2, 2, 2, 2)
        body_layout.setSpacing(10)
        self._form = DemandeForm(body)
        body_layout.addWidget(self._form)
        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch()

        self.cancel_btn = QPushButton(_TR("Cancel"), self)
        self.cancel_btn.setObjectName(self._cancel_object_name)
        self.cancel_btn.setProperty("immoVariant", "ghost")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setAccessibleName(_TR("Cancel"))

        self.save_btn = QPushButton(self._save_text, self)
        self.save_btn.setObjectName(self._save_object_name)
        self.save_btn.setProperty("immoVariant", "primary")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setAccessibleName(self._save_text)

        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.save_btn)
        root.addLayout(footer)

        self.setTabOrder(self._form.remarks, self.cancel_btn)
        self.setTabOrder(self.cancel_btn, self.save_btn)

    def _on_save(self) -> None:
        valid, message = self._form.validate()
        if not valid:
            QMessageBox.warning(self, _TR("Validation Error"), message)
            return
        self.accept()

    def get_data(self) -> dict[str, object]:
        """Return the normalized request payload from the form."""
        return self._form.get_data()
