"""
Audit settings dialog for configuring the default audit actor.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.agency_settings_repository import get_audit_actor_name, set_audit_actor_name
from app.services.db_core import set_audit_actor
from app.utils.i18n import tr_factory

_TR = tr_factory("AuditSettingsDialog")


class AuditSettingsDialog(QDialog):
    """Dialog for audit log settings (actor name)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_TR("Audit Settings"))
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)

        subtitle = QLabel(_TR("Set the default actor name used in audit logs."))
        layout.addWidget(subtitle)

        form = QFormLayout()
        self._actor_input = QLineEdit(self)
        self._actor_input.setText(get_audit_actor_name())
        self._actor_input.setPlaceholderText(_TR("e.g., Yacine"))
        self._actor_input.setToolTip(_TR("Name stored in audit logs for future changes."))
        self._actor_input.setAccessibleName(_TR("Audit actor name"))
        self._actor_input.setAccessibleDescription(
            _TR("Name stored in audit logs for future changes.")
        )
        form.addRow(_TR("Audit Actor:"), self._actor_input)
        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton(_TR("Save"))
        save_btn.setToolTip(_TR("Save audit actor name"))
        save_btn.setAccessibleName(_TR("Save audit actor"))
        save_btn.clicked.connect(self._save)

        cancel_btn = QPushButton(_TR("Cancel"))
        cancel_btn.setAccessibleName(_TR("Cancel"))
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.setTabOrder(self._actor_input, save_btn)
        self.setTabOrder(save_btn, cancel_btn)

    def _save(self) -> None:
        actor = self._actor_input.text().strip()
        set_audit_actor_name(actor)
        set_audit_actor(actor)
        self.accept()
