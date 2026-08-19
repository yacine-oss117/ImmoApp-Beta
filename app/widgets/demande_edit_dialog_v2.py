"""Client Request Edit Dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from app.models import Demande
from app.utils.i18n import tr_factory
from app.widgets.demande_request_dialog import DemandeRequestDialog

_TR = tr_factory("DemandeEditDialogV2")


class DemandeEditDialogV2(DemandeRequestDialog):
    """Edit a persisted client request using the shared modal request editor."""

    def __init__(self, demande: Demande, parent: QWidget | None = None) -> None:
        self._demande = demande
        super().__init__(
            demande,
            title=_TR("Edit Client Request"),
            save_text=_TR("Save"),
            save_object_name="demandeEditSaveButton",
            cancel_object_name="demandeEditCancelButton",
            parent=parent,
        )

    def get_data(self) -> dict[str, object]:
        data = super().get_data()
        data["row_version"] = self._demande.row_version
        return data
