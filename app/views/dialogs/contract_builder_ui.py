"""
UI builders for the contract builder dialog.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.constants import BUDGET_RANGE, SURFACE_RANGE
from app.utils.i18n import tr_factory

_TR = tr_factory("ContractBuilderUi")


@dataclass(frozen=True)
class ContractInfoWidgets:
    """Typed bundle of contract info form widgets."""

    property_type: QComboBox
    property_address: QLineEdit
    property_surface: QSpinBox
    owner_name: QLineEdit
    owner_address: QLineEdit
    tenant_name: QLineEdit
    tenant_address: QLineEdit
    start_date: QDateEdit
    end_date: QDateEdit
    monthly_rent: QSpinBox
    deposit: QSpinBox


@dataclass(frozen=True)
class ContractArticlesWidgets:
    """Typed bundle of article list widgets."""

    articles_container: QWidget
    articles_layout: QVBoxLayout
    add_button: QPushButton


def build_info_panel(parent: QWidget) -> tuple[QGroupBox, ContractInfoWidgets]:
    """Create the contract info panel and its widgets."""
    group = QGroupBox(_TR("Informations du Contrat"))
    group.setProperty("immoCard", True)
    group.setProperty("immoRole", "dialogPanel")
    layout = QFormLayout(group)
    layout.setSpacing(10)

    property_type = QComboBox(parent)
    property_type.setAccessibleName(_TR("Type de bien"))
    property_type.addItems(
        [_TR("Appartement"), _TR("Villa"), _TR("Local Commercial"), _TR("Terrain"), _TR("Studio")]
    )
    layout.addRow(_TR("Type de bien:"), property_type)

    property_address = QLineEdit(parent)
    property_address.setAccessibleName(_TR("Adresse du bien"))
    property_address.setPlaceholderText(_TR("Ex: 123 Rue Didouche Mourad, Alger"))
    layout.addRow(_TR("Adresse:"), property_address)

    property_surface = QSpinBox(parent)
    property_surface.setAccessibleName(_TR("Superficie"))
    surface_min = max(1, SURFACE_RANGE[0])
    property_surface.setRange(surface_min, SURFACE_RANGE[1])
    property_surface.setValue(80)
    property_surface.setSuffix(_TR(" m2"))
    layout.addRow(_TR("Superficie:"), property_surface)

    layout.addRow(QLabel(_TR("<b>Bailleur (Proprietaire)</b>")))
    owner_name = QLineEdit(parent)
    owner_name.setAccessibleName(_TR("Nom du bailleur"))
    layout.addRow(_TR("Nom:"), owner_name)

    owner_address = QLineEdit(parent)
    owner_address.setAccessibleName(_TR("Adresse du bailleur"))
    layout.addRow(_TR("Adresse:"), owner_address)

    layout.addRow(QLabel(_TR("<b>Locataire</b>")))
    tenant_name = QLineEdit(parent)
    tenant_name.setAccessibleName(_TR("Nom du locataire"))
    layout.addRow(_TR("Nom:"), tenant_name)

    tenant_address = QLineEdit(parent)
    tenant_address.setAccessibleName(_TR("Adresse du locataire"))
    layout.addRow(_TR("Adresse:"), tenant_address)

    layout.addRow(QLabel(_TR("<b>Conditions</b>")))

    start_date = QDateEdit(parent)
    start_date.setAccessibleName(_TR("Date de debut"))
    start_date.setDate(QDate.currentDate())
    start_date.setCalendarPopup(True)
    layout.addRow(_TR("Date debut:"), start_date)

    end_date = QDateEdit(parent)
    end_date.setAccessibleName(_TR("Date de fin"))
    end_date.setDate(QDate.currentDate().addYears(1))
    end_date.setCalendarPopup(True)
    layout.addRow(_TR("Date de fin:"), end_date)

    monthly_rent = QSpinBox(parent)
    monthly_rent.setAccessibleName(_TR("Loyer mensuel"))
    monthly_rent.setRange(*BUDGET_RANGE)
    monthly_rent.setSingleStep(1000)
    monthly_rent.setValue(50000)
    monthly_rent.setSuffix(_TR(" DA"))
    monthly_rent.setGroupSeparatorShown(True)
    layout.addRow(_TR("Loyer mensuel:"), monthly_rent)

    deposit = QSpinBox(parent)
    deposit.setAccessibleName(_TR("Caution"))
    deposit.setRange(*BUDGET_RANGE)
    deposit.setSingleStep(1000)
    deposit.setValue(50000)
    deposit.setSuffix(_TR(" DA"))
    deposit.setGroupSeparatorShown(True)
    layout.addRow(_TR("Caution:"), deposit)

    widgets = ContractInfoWidgets(
        property_type=property_type,
        property_address=property_address,
        property_surface=property_surface,
        owner_name=owner_name,
        owner_address=owner_address,
        tenant_name=tenant_name,
        tenant_address=tenant_address,
        start_date=start_date,
        end_date=end_date,
        monthly_rent=monthly_rent,
        deposit=deposit,
    )
    return group, widgets


def build_articles_panel(
    parent: QWidget,
    on_add_article: Callable[[], None],
) -> tuple[QGroupBox, ContractArticlesWidgets]:
    """Create the articles panel and its widgets."""
    group = QGroupBox(_TR("Articles du Contrat"))
    group.setProperty("immoCard", True)
    group.setProperty("immoRole", "dialogPanel")
    layout = QVBoxLayout(group)

    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setProperty("immoRole", "articleScroll")
    scroll.setAccessibleName(_TR("Contract articles list"))
    scroll.setAccessibleDescription(_TR("Scrollable list of contract articles."))

    articles_container = QWidget(scroll)
    articles_container.setAccessibleName(_TR("Contract articles container"))
    articles_layout = QVBoxLayout(articles_container)
    articles_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(articles_container)

    layout.addWidget(scroll, 1)

    add_btn = QPushButton(_TR("Ajouter un Article Personnalise"))
    add_btn.clicked.connect(on_add_article)
    add_btn.setAccessibleName(_TR("Ajouter un article"))
    add_btn.setProperty("immoVariant", "secondary")
    layout.addWidget(add_btn)

    widgets = ContractArticlesWidgets(
        articles_container=articles_container,
        articles_layout=articles_layout,
        add_button=add_btn,
    )
    return group, widgets
