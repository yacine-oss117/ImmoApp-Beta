"""
Article widget for the contract builder dialog.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("ContractBuilderArticle")


class ArticleWidget(QFrame):
    """Widget for a single contract article."""

    removed = Signal(int)  # Sends article_num

    def __init__(
        self,
        article_num: int,
        title: str,
        content: str,
        is_required: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.article_num = article_num
        self.is_required = is_required
        self.setProperty("immoCard", True)
        self.setProperty("immoRole", "contractArticle")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        header = QHBoxLayout()

        self._title_edit = QLineEdit(title, self)
        self._title_edit.setAccessibleName(_TR("Article title"))
        self._title_edit.setObjectName("contractArticleTitle")
        self._title_edit.setProperty("articleRole", "title")
        self._title_edit.setMinimumHeight(36)
        if is_required:
            self._title_edit.setReadOnly(True)
            self._title_edit.setProperty("articleRequired", True)
        header.addWidget(self._title_edit, 1)

        if not is_required:
            remove_btn = QPushButton("X")
            remove_btn.setFixedSize(24, 24)
            remove_btn.setToolTip(_TR("Supprimer cet article"))
            remove_btn.setAccessibleName(_TR("Remove article"))
            remove_btn.setProperty("immoVariant", "danger")
            remove_btn.setProperty("immoRole", "tinyAction")
            remove_btn.clicked.connect(self._on_remove)
            header.addWidget(remove_btn)
        else:
            required_label = QLabel("!")
            required_label.setToolTip(_TR("Article obligatoire"))
            required_label.setAccessibleName(_TR("Required article"))
            required_label.setProperty("articleRole", "requiredFlag")
            header.addWidget(required_label)

        layout.addLayout(header)

        self._content_edit = QTextEdit(self)
        self._content_edit.setPlainText(content)
        self._content_edit.setAccessibleName(_TR("Article content"))
        self._content_edit.setProperty("articleRole", "content")
        if is_required:
            self._content_edit.setReadOnly(True)
            self._content_edit.setProperty("articleRequired", True)
        self._content_edit.setMinimumHeight(80)
        layout.addWidget(self._content_edit)

    def _on_remove(self) -> None:
        self.removed.emit(self.article_num)

    def get_data(self) -> dict[str, object]:
        return {
            "article_num": self.article_num,
            "title": self._title_edit.text(),
            "content": self._content_edit.toPlainText(),
            "is_required": self.is_required,
        }
