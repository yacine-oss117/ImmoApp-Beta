"""
WhatsApp Templates Dialog - Manage message templates.

Allows users to:
- View all templates (default + custom)
- Add new custom templates
- Edit existing templates
- Preview templates with sample data
- Delete custom templates (defaults are read-only)
"""

import logging
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QWidget,
)

from app.services.wa_templates_repository import (
    create_template,
    delete_template,
    get_all_templates,
    get_template_by_id,
    render_template,
    update_template,
)
from app.shared_types import TemplateContext
from app.utils.i18n import tr_factory
from app.utils.text_safety import set_label_plain_text
from app.utils.wa_templates import build_template_context
from app.views.dialogs.wa_templates_ui import setup_wa_templates_ui

logger = logging.getLogger(__name__)
_TR = tr_factory("WaTemplatesDialog")


class WaTemplatesDialog(QDialog):
    """Dialog for managing WhatsApp templates."""

    _template_list: QListWidget
    _name_edit: QLineEdit
    _content_edit: QTextEdit
    _preview_text: QLabel
    _save_btn: QPushButton
    _delete_btn: QPushButton

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_template_id: int | None = None
        setup_wa_templates_ui(self)
        self._load_templates()

    def _load_templates(self) -> None:
        """Load all templates into the list."""
        self._template_list.clear()
        templates = get_all_templates()

        for tpl in templates:
            item = QListWidgetItem()
            prefix = _TR("[Default] ") if tpl.get("is_default") else _TR("[Custom] ")
            item.setText(f"{prefix}{tpl['name']}")
            item.setData(int(Qt.ItemDataRole.UserRole), tpl["id"])
            self._template_list.addItem(item)

        if templates:
            self._template_list.setCurrentRow(0)

    def _on_template_selected(self, row: int) -> None:
        """Handle template selection."""
        if row < 0:
            return

        item = self._template_list.item(row)
        template_id_obj = item.data(int(Qt.ItemDataRole.UserRole))
        if template_id_obj is None:
            return
        template_id = int(template_id_obj)
        self._current_template_id = template_id

        tpl = get_template_by_id(template_id)
        if tpl:
            self._name_edit.setText(str(tpl["name"]))
            self._content_edit.setPlainText(str(tpl["template"]))
            self._delete_btn.setEnabled(not tpl.get("is_default", False))
            self._update_preview()

    def _update_preview(self) -> None:
        """Update the preview with sample data."""
        content = self._content_edit.toPlainText()

        # Sample data for preview
        sample_context: TemplateContext = build_template_context(
            client_name="Ahmed Benali",
            location="Bab Ezzouar, Algiers",
            price="8,500,000",
            property_type="Apartment F3",
            agency_name="Century 21 Algiers",
            date="20/12/2024",
            time="14:00",
        )
        rendered = render_template(
            content,
            cast(dict[str, str], sample_context),
        )
        set_label_plain_text(self._preview_text, rendered)

    def _on_add(self) -> None:
        """Add a new template."""
        self._current_template_id = None
        self._name_edit.clear()
        self._content_edit.clear()
        self._name_edit.setFocus()
        self._delete_btn.setEnabled(False)

    def _on_save(self) -> None:
        """Save the current template."""
        name = self._name_edit.text().strip()
        content = self._content_edit.toPlainText().strip()

        try:
            if self._current_template_id:
                # Update existing
                update_template(self._current_template_id, name, content)
                QMessageBox.information(self, _TR("Success"), _TR("Template updated."))
            else:
                # Create new
                new_id = create_template(name, content)
                self._current_template_id = new_id
                QMessageBox.information(self, _TR("Success"), _TR("Template created."))

            self._load_templates()
        except Exception as e:
            logger.error("Template save failed", exc_info=True)
            QMessageBox.critical(self, _TR("Error"), _TR("Save failed: {error}").format(error=e))

    def _on_delete(self) -> None:
        """Delete the current template."""
        if not self._current_template_id:
            return

        reply = QMessageBox.question(
            self,
            _TR("Confirm"),
            _TR("Delete this template?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if delete_template(self._current_template_id):
                self._current_template_id = None
                self._load_templates()
                QMessageBox.information(self, _TR("Success"), _TR("Template deleted."))
            else:
                QMessageBox.warning(
                    self,
                    _TR("Error"),
                    _TR("Unable to delete this template (default template)."),
                )
