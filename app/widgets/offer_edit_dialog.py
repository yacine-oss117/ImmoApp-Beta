"""
Property Offer Edit Dialog.

Features:
- Wilaya dropdown with prefix search (FIXED list)
- Location/Commune dropdown - CASCADING (filtered by selected wilaya)
- Same fields as OfferPanel: type, action, beds, surface, budget, furnished, floor, elevator, link
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from app.models import Offer
from app.utils.i18n import tr_factory
from app.widgets.offer_form import OfferForm

_TR = tr_factory("OfferEditDialog")


class OfferEditDialog(QDialog):
    """
    Edit dialog for offers with proper Wilaya + cascading Location fields.

    Same form structure as OfferPanel for consistency.
    """

    def __init__(self, offer: Offer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._offer = offer
        self._setup_ui()
        self._load_data()

    def _setup_ui(self) -> None:
        self.setWindowTitle(_TR("Edit Property Offer"))
        self.setMinimumWidth(760)
        self.setModal(True)
        self.setObjectName("immoDialog")
        self.setAccessibleName(_TR("Edit property offer dialog"))

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._form = OfferForm(self)
        layout.addWidget(self._form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.save_btn = QPushButton(_TR("Save"))
        self.save_btn.setObjectName("offerEditSaveButton")
        self.save_btn.setProperty("immoVariant", "primary")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setAccessibleName(_TR("Save property offer"))

        self.cancel_btn = QPushButton(_TR("Cancel"))
        self.cancel_btn.setObjectName("offerEditCancelButton")
        self.cancel_btn.setProperty("immoVariant", "ghost")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setAccessibleName(_TR("Cancel"))

        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        self.setTabOrder(self._form.remarks, self.save_btn)
        self.setTabOrder(self.save_btn, self.cancel_btn)

    def _on_save(self) -> None:
        self.accept()

    def _load_data(self) -> None:
        """Load offer data into form."""
        self._form.set_data(self._offer)

    def get_data(self) -> dict[str, object]:
        """Get form data as dictionary."""
        data = self._form.get_data()
        data["row_version"] = self._offer.row_version
        return data
