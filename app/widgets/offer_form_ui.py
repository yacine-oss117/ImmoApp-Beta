"""UI builder for OfferForm."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.constants import (
    BEDS_RANGE,
    BUDGET_RANGE,
    FLEX_RANGE,
    FLOOR_RANGE,
    LISTING_ACTIONS,
    LISTING_FURNISHED,
    LISTING_TYPES,
    SURFACE_RANGE,
)
from app.services.locations import get_wilaya_labels
from app.utils.i18n import tr_factory
from app.widgets.form_section import build_form_section
from app.widgets.location_multi_select import LocationMultiSelect
from app.widgets.offer_form_labels import ACTION_LABELS, FURNISHED_LABELS, TYPE_LABELS
from app.widgets.prefix_combo import PrefixComboBox

_TR = tr_factory("OfferForm")

if TYPE_CHECKING:
    from app.widgets.offer_form import OfferForm


def setup_offer_form(form: OfferForm) -> None:
    """Build and wire the OfferForm widgets."""
    layout = QVBoxLayout(form)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    form.type = QComboBox()
    form.type.setObjectName("offerTypeCombo")
    form._populate_combo(form.type, LISTING_TYPES, TYPE_LABELS)
    form.type.currentTextChanged.connect(form._on_type_changed)
    form.type.currentTextChanged.connect(form._emit_changed)
    form.type.setAccessibleName(_TR("Property type"))

    form.action = QComboBox()
    form.action.setObjectName("offerActionCombo")
    form._populate_combo(form.action, LISTING_ACTIONS, ACTION_LABELS)
    form.action.currentTextChanged.connect(form._emit_changed)
    form.action.setAccessibleName(_TR("Listing goal"))

    form.wilaya = PrefixComboBox(force_selection=True, allow_add=False)
    form.wilaya.setObjectName("offerWilayaCombo")
    wilaya_edit = form.wilaya.lineEdit()
    if wilaya_edit is not None:
        wilaya_edit.setObjectName("offerWilayaInput")
    form.wilaya.setItems(get_wilaya_labels())
    form.wilaya.textChanged.connect(form._on_wilaya_changed)
    form.wilaya.textChanged.connect(form._emit_changed)
    form.wilaya.setAccessibleName(_TR("City"))

    form.location = LocationMultiSelect(allow_add=True)
    form.location.setObjectName("offerLocationInput")
    form.location.set_automation_prefix("offerLocation")
    form.location.setItems([])
    form.location.setOnAddCallback(form._on_add_location)
    form.location.itemsChanged.connect(form._refresh_locations)
    form.location.valueChanged.connect(form._emit_changed)
    form.location.setAccessibleName(_TR("Areas"))
    form.location.setAccessibleDescription(_TR("Selected areas for this property."))
    form._all_locations = []

    form.beds = QSpinBox()
    form.beds.setObjectName("offerBedsInput")
    form.beds.lineEdit().setObjectName("offerBedsInputEdit")
    form.beds.setRange(*BEDS_RANGE)
    form.beds.valueChanged.connect(form._emit_changed)
    form.beds.setAccessibleName(_TR("Bedrooms"))

    form.surface = QDoubleSpinBox()
    form.surface.setObjectName("offerSurfaceInput")
    form.surface.lineEdit().setObjectName("offerSurfaceInputEdit")
    form.surface.setRange(*SURFACE_RANGE)
    form.surface.setGroupSeparatorShown(True)
    form.surface.setSuffix(_TR(" m²"))
    form.surface.valueChanged.connect(form._emit_changed)
    form.surface.setAccessibleName(_TR("Size"))

    form.budget = QDoubleSpinBox()
    form.budget.setObjectName("offerBudgetInput")
    form.budget.lineEdit().setObjectName("offerBudgetInputEdit")
    form.budget.setRange(*BUDGET_RANGE)
    form.budget.setGroupSeparatorShown(True)
    form.budget.setSuffix(_TR(" DZD"))
    form.budget.valueChanged.connect(form._emit_changed)
    form.budget.setAccessibleName(_TR("Price"))

    form.price_negotiable = QCheckBox(_TR("Negotiable"))
    form.price_negotiable.setObjectName("offerPriceNegotiableCheck")
    form.price_negotiable.stateChanged.connect(form._emit_changed)
    form.price_negotiable.setAccessibleName(_TR("Price is negotiable"))

    form.price_flex_pct = QLineEdit()
    form.price_flex_pct.setObjectName("offerPriceFlexInput")
    form.price_flex_pct.setValidator(
        QDoubleValidator(float(FLEX_RANGE[0]), float(FLEX_RANGE[1]), 0, form.price_flex_pct)
    )
    form.price_flex_pct.setPlaceholderText("0")
    form.price_flex_pct.setAccessibleName(_TR("Negotiation margin"))
    form.price_flex_pct.setToolTip(_TR("How much the price can move during negotiation (0-100%)"))
    form.price_flex_pct.textChanged.connect(form._emit_changed)

    form.furnished = QComboBox()
    form.furnished.setObjectName("offerFurnishedCombo")
    form._populate_combo(form.furnished, LISTING_FURNISHED, FURNISHED_LABELS)
    form.furnished.currentTextChanged.connect(form._emit_changed)
    form.furnished.setAccessibleName(_TR("Furnished"))

    form.floor = QSpinBox()
    form.floor.setObjectName("offerFloorInput")
    form.floor.lineEdit().setObjectName("offerFloorInputEdit")
    form.floor.setRange(*FLOOR_RANGE)
    form.floor.valueChanged.connect(form._emit_changed)
    form.floor.setAccessibleName(_TR("Floor"))
    form.floor_label = QLabel(_TR("Floor"))

    form.elevator = QCheckBox(_TR("Has Elevator"))
    form.elevator.setObjectName("offerElevatorCheck")
    form.elevator.stateChanged.connect(form._emit_changed)
    form.elevator.setAccessibleName(_TR("Has elevator"))

    form.accessibility_supported = QCheckBox(_TR("Accessibility ♿"))
    form.accessibility_supported.setObjectName("offerAccessibilityCheck")
    form.accessibility_supported.stateChanged.connect(form._emit_changed)
    form.accessibility_supported.setAccessibleName(_TR("Accessibility supported"))

    form.link = QLineEdit()
    form.link.setObjectName("offerLinkInput")
    form.link.setPlaceholderText(_TR("URL or coordinates"))
    form.link.textChanged.connect(form._on_link_changed)
    form.link.setAccessibleName(_TR("Map link"))

    form.latitude = QLineEdit()
    form.latitude.setObjectName("offerLatitudeInput")
    form.latitude.setPlaceholderText(_TR("Latitude"))
    form.latitude.setAccessibleName(_TR("Latitude"))
    lat_validator = QDoubleValidator(-90.0, 90.0, 6, form.latitude)
    lat_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    form.latitude.setValidator(lat_validator)
    form.latitude.textChanged.connect(form._on_coords_changed)

    form.longitude = QLineEdit()
    form.longitude.setObjectName("offerLongitudeInput")
    form.longitude.setPlaceholderText(_TR("Longitude"))
    form.longitude.setAccessibleName(_TR("Longitude"))
    lon_validator = QDoubleValidator(-180.0, 180.0, 6, form.longitude)
    lon_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    form.longitude.setValidator(lon_validator)
    form.longitude.textChanged.connect(form._on_coords_changed)

    form.extract_coords_btn = QPushButton(_TR("Extract"))
    form.extract_coords_btn.setObjectName("offerExtractCoordsButton")
    form.extract_coords_btn.setAccessibleName(_TR("Extract coordinates"))
    form.extract_coords_btn.clicked.connect(form._extract_coords_from_link)
    form.extract_coords_btn.setProperty("immoVariant", "secondary")

    form.open_map_btn = QPushButton(_TR("View Map"))
    form.open_map_btn.setObjectName("offerOpenMapButton")
    form.open_map_btn.setAccessibleName(_TR("Open map"))
    form.open_map_btn.clicked.connect(form._open_map_in_browser)
    form.open_map_btn.setProperty("immoVariant", "ghost")

    form.remarks = QLineEdit()
    form.remarks.setObjectName("offerRemarksInput")
    form.remarks.setPlaceholderText(_TR("Additional notes..."))
    form.remarks.textChanged.connect(form._emit_changed)
    form.remarks.setAccessibleName(_TR("Notes"))

    coords_row = QWidget(form)
    coords_layout = QHBoxLayout(coords_row)
    coords_layout.setContentsMargins(0, 0, 0, 0)
    coords_layout.setSpacing(8)
    coords_layout.addWidget(form.latitude)
    coords_layout.addWidget(form.longitude)
    coords_layout.addWidget(form.extract_coords_btn)
    coords_layout.addWidget(form.open_map_btn)

    budget_row = QWidget(form)
    budget_layout = QHBoxLayout(budget_row)
    budget_layout.setContentsMargins(0, 0, 0, 0)
    budget_layout.setSpacing(8)
    budget_layout.addWidget(form.budget)
    budget_layout.addWidget(form.price_negotiable)
    budget_layout.addWidget(QLabel(_TR("Negotiation margin:")))
    budget_layout.addWidget(form.price_flex_pct)
    budget_layout.addStretch()

    identity_box, identity_grid = build_form_section(form, _TR("Property Basics"))
    identity_grid.addWidget(QLabel(_TR("Type")), 0, 0)
    identity_grid.addWidget(form.type, 0, 1)
    identity_grid.addWidget(QLabel(_TR("For")), 0, 2)
    identity_grid.addWidget(form.action, 0, 3)
    identity_grid.addWidget(QLabel(_TR("City")), 1, 0)
    identity_grid.addWidget(form.wilaya, 1, 1)
    identity_grid.addWidget(QLabel(_TR("Areas")), 1, 2)
    identity_grid.addWidget(form.location, 1, 3)
    identity_grid.setColumnStretch(1, 1)
    identity_grid.setColumnStretch(3, 1)

    constraints_box, constraints_grid = build_form_section(form, _TR("Property Details"))
    constraints_grid.addWidget(QLabel(_TR("Bedrooms")), 0, 0)
    constraints_grid.addWidget(form.beds, 0, 1)
    constraints_grid.addWidget(QLabel(_TR("Furnished")), 0, 2)
    constraints_grid.addWidget(form.furnished, 0, 3)
    constraints_grid.addWidget(QLabel(_TR("Size")), 1, 0)
    constraints_grid.addWidget(form.surface, 1, 1)
    constraints_grid.addWidget(QLabel(_TR("Price")), 1, 2)
    constraints_grid.addWidget(budget_row, 1, 3)
    constraints_grid.addWidget(form.floor_label, 2, 0)
    constraints_grid.addWidget(form.floor, 2, 1)
    constraints_grid.addWidget(form.elevator, 2, 2, 1, 2)
    constraints_grid.addWidget(form.accessibility_supported, 3, 0, 1, 4)
    constraints_grid.setColumnStretch(1, 1)
    constraints_grid.setColumnStretch(3, 1)

    geo_box, geo_grid = build_form_section(form, _TR("Location & Notes"))
    geo_grid.addWidget(QLabel(_TR("Map link")), 0, 0)
    geo_grid.addWidget(form.link, 0, 1, 1, 3)
    geo_grid.addWidget(QLabel(_TR("Coordinates")), 1, 0)
    geo_grid.addWidget(coords_row, 1, 1, 1, 3)
    geo_grid.addWidget(QLabel(_TR("Notes")), 2, 0)
    geo_grid.addWidget(form.remarks, 2, 1, 1, 3)
    geo_grid.setColumnStretch(1, 1)
    geo_grid.setColumnStretch(3, 1)

    layout.addWidget(identity_box)
    layout.addWidget(constraints_box)
    layout.addWidget(geo_box)

    form.setTabOrder(form.type, form.action)
    form.setTabOrder(form.action, form.wilaya)
    form.setTabOrder(form.wilaya, form.location)
    form.setTabOrder(form.location, form.beds)
    form.setTabOrder(form.beds, form.surface)
    form.setTabOrder(form.surface, form.budget)
    form.setTabOrder(form.budget, form.furnished)
    form.setTabOrder(form.furnished, form.floor)
    form.setTabOrder(form.floor, form.elevator)
    form.setTabOrder(form.elevator, form.accessibility_supported)
    form.setTabOrder(form.accessibility_supported, form.link)
    form.setTabOrder(form.link, form.latitude)
    form.setTabOrder(form.latitude, form.longitude)
    form.setTabOrder(form.longitude, form.extract_coords_btn)
    form.setTabOrder(form.extract_coords_btn, form.open_map_btn)
    form.setTabOrder(form.open_map_btn, form.remarks)

    form._on_type_changed(form.type.currentText())
