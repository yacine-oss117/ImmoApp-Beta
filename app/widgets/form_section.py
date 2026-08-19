"""Reusable section shell for editor forms."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget


class FormSection(QFrame):
    """A small themed section wrapper with a title and content grid."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("immoFormSection")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("immoFormSectionTitle")
        root.addWidget(self.title_label)

        self.content_layout = QGridLayout()
        self.content_layout.setContentsMargins(6, 2, 6, 6)
        self.content_layout.setHorizontalSpacing(12)
        self.content_layout.setVerticalSpacing(10)
        root.addLayout(self.content_layout)


def build_form_section(parent: QWidget, title: str) -> tuple[FormSection, QGridLayout]:
    """Factory helper used by demande/offer builders."""
    section = FormSection(title, parent)
    return section, section.content_layout
