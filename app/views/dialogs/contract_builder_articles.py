"""
Article management and context assembly for contract builder.
"""

from __future__ import annotations

from typing import cast

from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.services.agency_settings_repository import get_agency_name
from app.services.standard_clauses import get_standard_clauses, render_all_clauses
from app.utils.common import fmt_int_group
from app.utils.i18n import tr_factory
from app.views.dialogs.contract_builder_article import ArticleWidget

_TR = tr_factory("ContractBuilderDialog")


class ContractBuilderArticleMixin:
    """Behavior mixin for article management and context."""

    _articles: list[ArticleWidget]
    _articles_container: QWidget
    _articles_layout: QVBoxLayout
    _owner_name: QLineEdit
    _owner_address: QLineEdit
    _tenant_name: QLineEdit
    _tenant_address: QLineEdit
    _property_address: QLineEdit
    _property_type: QComboBox
    _property_surface: QSpinBox
    _start_date: QDateEdit
    _end_date: QDateEdit
    _monthly_rent: QSpinBox
    _deposit: QSpinBox

    def _load_standard_clauses(self) -> None:
        """Load the 10 standard Algerian clauses."""
        self._clear_articles()

        context = self._get_context()
        clauses = get_standard_clauses()
        rendered = render_all_clauses(clauses, context)

        for clause in rendered:
            widget = ArticleWidget(
                article_num=clause["number"],
                title=_TR("Article {num} - {title}").format(
                    num=clause["number"], title=clause["title"]
                ),
                content=clause["content"],
                is_required=clause.get("is_required", False),
                parent=self._articles_container,
            )
            self._articles_layout.addWidget(widget)
            self._articles.append(widget)
            widget.removed.connect(self._on_article_removed)

        QMessageBox.information(
            cast(QWidget, self),
            _TR("Succes"),
            _TR("Clauses standard chargees."),
        )

    def _add_custom_article(self) -> None:
        """Add a new custom article."""
        next_num = len(self._articles) + 1
        widget = ArticleWidget(
            article_num=next_num,
            title=_TR("Article {num} - ").format(num=next_num),
            content="",
            is_required=False,
            parent=self._articles_container,
        )
        self._articles_layout.addWidget(widget)
        self._articles.append(widget)
        widget.removed.connect(self._on_article_removed)

    def _on_article_removed(self, article_num: int) -> None:
        """Handle article removal safely."""
        params = [w for w in self._articles if w.article_num == article_num]
        if not params:
            return

        widget = params[0]
        self._articles.remove(widget)
        widget.setParent(None)
        widget.deleteLater()

        for i, w in enumerate(self._articles, 1):
            w.article_num = i
            current_title = w._title_edit.text()
            article_label = _TR("Article")
            if current_title.startswith(article_label) and "-" in current_title:
                parts = current_title.split("-", 1)
                w._title_edit.setText(
                    _TR("{label} {num} -{rest}").format(label=article_label, num=i, rest=parts[1])
                )

    def _clear_articles(self) -> None:
        """Clear all articles."""
        for widget in self._articles:
            widget.setParent(None)
            widget.deleteLater()
        self._articles.clear()

    def _get_context(self) -> dict[str, str]:
        """Get context for placeholder rendering."""
        return {
            "owner_name": self._owner_name.text() or "________",
            "owner_address": self._owner_address.text() or "________",
            "tenant_name": self._tenant_name.text() or "________",
            "tenant_address": self._tenant_address.text() or "________",
            "property_address": self._property_address.text() or "________",
            "property_type": self._property_type.currentText(),
            "property_surface": str(self._property_surface.value()),
            "lease_start": self._start_date.date().toString("dd/MM/yyyy"),
            "lease_end": self._end_date.date().toString("dd/MM/yyyy"),
            "monthly_rent": fmt_int_group(self._monthly_rent.value()),
            "security_deposit": fmt_int_group(self._deposit.value()),
            "agency_name": get_agency_name(),
        }

    def _get_articles_data(self) -> list[dict[str, object]]:
        """Get all article data, renumbering sequentially."""
        articles = []
        for i, widget in enumerate(self._articles, start=1):
            if widget.parent():
                data = widget.get_data()
                data["article_number"] = i
                articles.append(data)
        return articles
