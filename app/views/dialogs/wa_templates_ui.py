"""UI builder for WhatsApp templates dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("WaTemplatesDialog")

if TYPE_CHECKING:
    from app.views.dialogs.wa_templates_dialog import WaTemplatesDialog


def setup_wa_templates_ui(dialog: WaTemplatesDialog) -> None:
    """Build UI controls and attach them to the dialog."""
    dialog.setWindowTitle(_TR("Message Templates"))
    dialog.setMinimumSize(700, 500)
    dialog.setModal(True)
    dialog.setObjectName("immoDialog")

    layout = QHBoxLayout(dialog)

    left_panel = QVBoxLayout()
    left_panel.addWidget(QLabel(_TR("<b>Available templates:</b>")))

    dialog._template_list = QListWidget(dialog)
    dialog._template_list.currentRowChanged.connect(dialog._on_template_selected)
    dialog._template_list.setAccessibleName(_TR("Templates list"))
    dialog._template_list.setAccessibleDescription(
        _TR("List of default and custom WhatsApp templates.")
    )
    left_panel.addWidget(dialog._template_list)

    add_btn = QPushButton(_TR("Add Template"))
    add_btn.clicked.connect(dialog._on_add)
    add_btn.setAccessibleName(_TR("Add template"))
    add_btn.setProperty("immoVariant", "secondary")
    left_panel.addWidget(add_btn)

    left_widget = QWidget(dialog)
    left_widget.setLayout(left_panel)
    left_widget.setMaximumWidth(250)
    left_widget.setProperty("immoCard", True)
    left_widget.setProperty("immoRole", "dialogPanel")

    right_panel = QVBoxLayout()

    name_layout = QHBoxLayout()
    name_layout.addWidget(QLabel(_TR("Name:")))
    dialog._name_edit = QLineEdit(dialog)
    dialog._name_edit.setPlaceholderText(_TR("Example: New Listing"))
    dialog._name_edit.setAccessibleName(_TR("Template name"))
    dialog._name_edit.setAccessibleDescription(_TR("Template name input."))
    name_layout.addWidget(dialog._name_edit)
    right_panel.addLayout(name_layout)

    right_panel.addWidget(QLabel(_TR("Message content:")))
    dialog._content_edit = QTextEdit(dialog)
    dialog._content_edit.setPlaceholderText(
        _TR(
            "Use variables:\n"
            "{client_name} - Client name\n"
            "{type} - Property type\n"
            "{location} - Location\n"
            "{price} - Price\n"
            "{date} - Date\n"
            "{time} - Time\n"
            "{agency_name} - Agency name"
        )
    )
    dialog._content_edit.setAccessibleName(_TR("Template content"))
    dialog._content_edit.setAccessibleDescription(_TR("WhatsApp template content editor."))
    right_panel.addWidget(dialog._content_edit)

    preview_group = QGroupBox(_TR("Preview"))
    preview_layout = QVBoxLayout(preview_group)

    dialog._preview_text = QLabel(dialog)
    dialog._preview_text.setWordWrap(True)
    dialog._preview_text.setAccessibleName(_TR("Template preview"))
    dialog._preview_text.setObjectName("waTemplatePreview")
    preview_layout.addWidget(dialog._preview_text)

    preview_btn = QPushButton(_TR("Refresh Preview"))
    preview_btn.clicked.connect(dialog._update_preview)
    preview_btn.setAccessibleName(_TR("Refresh preview"))
    preview_layout.addWidget(preview_btn)

    right_panel.addWidget(preview_group)

    btn_layout = QHBoxLayout()

    dialog._save_btn = QPushButton(_TR("Save"))
    dialog._save_btn.clicked.connect(dialog._on_save)
    dialog._save_btn.setAccessibleName(_TR("Save template"))
    dialog._save_btn.setProperty("immoVariant", "primary")

    dialog._delete_btn = QPushButton(_TR("Delete"))
    dialog._delete_btn.clicked.connect(dialog._on_delete)
    dialog._delete_btn.setAccessibleName(_TR("Delete template"))
    dialog._delete_btn.setProperty("immoVariant", "danger")

    close_btn = QPushButton(_TR("Close"))
    close_btn.clicked.connect(dialog.accept)
    close_btn.setAccessibleName(_TR("Close"))
    close_btn.setProperty("immoVariant", "ghost")

    btn_layout.addWidget(dialog._save_btn)
    btn_layout.addWidget(dialog._delete_btn)
    btn_layout.addStretch()
    btn_layout.addWidget(close_btn)

    right_panel.addLayout(btn_layout)

    right_widget = QWidget(dialog)
    right_widget.setLayout(right_panel)
    right_widget.setProperty("immoCard", True)
    right_widget.setProperty("immoRole", "dialogPanel")

    layout.addWidget(left_widget)
    layout.addWidget(right_widget, 1)

    dialog.setTabOrder(dialog._template_list, dialog._name_edit)
    dialog.setTabOrder(dialog._name_edit, dialog._content_edit)
    dialog.setTabOrder(dialog._content_edit, preview_btn)
    dialog.setTabOrder(preview_btn, dialog._save_btn)
    dialog.setTabOrder(dialog._save_btn, dialog._delete_btn)
    dialog.setTabOrder(dialog._delete_btn, close_btn)
