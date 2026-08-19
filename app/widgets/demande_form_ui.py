"""UI builder for DemandeForm."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.constants import (
    BEDS_RANGE,
    BUDGET_RANGE,
    CLIENT_ACTIONS,
    CLIENT_FURNISHED,
    CLIENT_TYPES,
    FLOOR_RANGE,
    SURFACE_RANGE,
)
from app.services.locations import get_wilaya_labels
from app.utils.i18n import tr_factory
from app.widgets.demande_form_labels import ACTION_LABELS, FURNISHED_LABELS, TYPE_LABELS
from app.widgets.form_section import build_form_section
from app.widgets.location_multi_select import LocationMultiSelect
from app.widgets.prefix_combo import PrefixComboBox

_TR = tr_factory("DemandeForm")

if TYPE_CHECKING:
    from app.widgets.demande_form import DemandeForm


def setup_demande_form(form: DemandeForm) -> None:
    """Build and wire the DemandeForm widgets."""
    layout = QVBoxLayout(form)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    form.type = QComboBox()
    form.type.setObjectName("demandeTypeCombo")
    form._populate_combo(form.type, CLIENT_TYPES, TYPE_LABELS)
    form.type.currentTextChanged.connect(form._on_type_changed)
    form.type.currentTextChanged.connect(form._emit_changed)
    form.type.setAccessibleName(_TR("Property type"))

    form.action = QComboBox()
    form.action.setObjectName("demandeActionCombo")
    form._populate_combo(form.action, CLIENT_ACTIONS, ACTION_LABELS)
    form.action.currentTextChanged.connect(form._emit_changed)
    form.action.setAccessibleName(_TR("Looking for"))

    form.wilaya = PrefixComboBox(force_selection=True, allow_add=False)
    form.wilaya.setObjectName("demandeWilayaCombo")
    wilaya_edit = form.wilaya.lineEdit()
    if wilaya_edit is not None:
        wilaya_edit.setObjectName("demandeWilayaInput")
    form.wilaya.setItems(get_wilaya_labels())
    form.wilaya.textChanged.connect(form._on_wilaya_changed)
    form.wilaya.textChanged.connect(form._emit_changed)
    form.wilaya.setAccessibleName(_TR("City"))

    form.location = LocationMultiSelect(allow_add=True)
    form.location.setObjectName("demandeLocationsInput")
    form.location.set_automation_prefix("demandeLocations")
    form.location.setItems([])
    form.location.setOnAddCallback(form._on_add_location)
    form.location.itemsChanged.connect(form._refresh_locations)
    form.location.valueChanged.connect(form._emit_changed)
    form.location.setAccessibleName(_TR("Areas"))
    form.location.setAccessibleDescription(_TR("Selected areas for this request."))
    form._all_locations = []

    form.beds_min = QSpinBox()
    form.beds_min.setObjectName("demandeBedsMinInput")
    form.beds_min.lineEdit().setObjectName("demandeBedsMinInputEdit")
    form.beds_min.setRange(*BEDS_RANGE)
    form.beds_min.valueChanged.connect(form._emit_changed)
    form.beds_min.setAccessibleName(_TR("Minimum bedrooms"))

    form.surface_min = QDoubleSpinBox()
    form.surface_min.setObjectName("demandeSurfaceMinInput")
    form.surface_min.lineEdit().setObjectName("demandeSurfaceMinInputEdit")
    form.surface_min.setRange(*SURFACE_RANGE)
    form.surface_min.setGroupSeparatorShown(True)
    form.surface_min.setSuffix(_TR(" m²"))
    form.surface_min.valueChanged.connect(form._emit_changed)
    form.surface_min.setAccessibleName(_TR("Minimum surface"))

    form.surface_max = QDoubleSpinBox()
    form.surface_max.setObjectName("demandeSurfaceMaxInput")
    form.surface_max.lineEdit().setObjectName("demandeSurfaceMaxInputEdit")
    form.surface_max.setRange(*SURFACE_RANGE)
    form.surface_max.setGroupSeparatorShown(True)
    form.surface_max.setSuffix(_TR(" m²"))
    form.surface_max.valueChanged.connect(form._emit_changed)
    form.surface_max.setAccessibleName(_TR("Maximum surface"))

    surface_row = QWidget(form)
    surface_layout = QHBoxLayout(surface_row)
    surface_layout.setContentsMargins(0, 0, 0, 0)
    surface_layout.setSpacing(8)
    surface_layout.addWidget(form.surface_min)
    surface_layout.addWidget(QLabel(_TR("to")))
    surface_layout.addWidget(form.surface_max)

    form.budget_min = QDoubleSpinBox()
    form.budget_min.setObjectName("demandeBudgetMinInput")
    form.budget_min.lineEdit().setObjectName("demandeBudgetMinInputEdit")
    form.budget_min.setRange(*BUDGET_RANGE)
    form.budget_min.setGroupSeparatorShown(True)
    form.budget_min.setSuffix(_TR(" DZD"))
    form.budget_min.valueChanged.connect(form._emit_changed)
    form.budget_min.setAccessibleName(_TR("Minimum budget"))

    form.budget_max = QDoubleSpinBox()
    form.budget_max.setObjectName("demandeBudgetMaxInput")
    form.budget_max.lineEdit().setObjectName("demandeBudgetMaxInputEdit")
    form.budget_max.setRange(*BUDGET_RANGE)
    form.budget_max.setGroupSeparatorShown(True)
    form.budget_max.setSuffix(_TR(" DZD"))
    form.budget_max.valueChanged.connect(form._emit_changed)
    form.budget_max.setAccessibleName(_TR("Maximum budget"))

    budget_row = QWidget(form)
    budget_layout = QHBoxLayout(budget_row)
    budget_layout.setContentsMargins(0, 0, 0, 0)
    budget_layout.setSpacing(8)
    budget_layout.addWidget(form.budget_min)
    budget_layout.addWidget(QLabel(_TR("to")))
    budget_layout.addWidget(form.budget_max)

    form.furnished = QComboBox()
    form.furnished.setObjectName("demandeFurnishedCombo")
    form._populate_combo(form.furnished, CLIENT_FURNISHED, FURNISHED_LABELS)
    form.furnished.currentTextChanged.connect(form._emit_changed)
    form.furnished.setAccessibleName(_TR("Furnished"))

    form.floor_min = QSpinBox()
    form.floor_min.setObjectName("demandeFloorMinInput")
    form.floor_min.lineEdit().setObjectName("demandeFloorMinInputEdit")
    form.floor_min.setRange(*FLOOR_RANGE)
    form.floor_min.valueChanged.connect(form._emit_changed)
    form.floor_min.setAccessibleName(_TR("Minimum floor"))

    form.floor_max = QSpinBox()
    form.floor_max.setObjectName("demandeFloorMaxInput")
    form.floor_max.lineEdit().setObjectName("demandeFloorMaxInputEdit")
    form.floor_max.setRange(*FLOOR_RANGE)
    form.floor_max.setValue(100)
    form.floor_max.valueChanged.connect(form._emit_changed)
    form.floor_max.setAccessibleName(_TR("Maximum floor"))

    floor_row = QWidget(form)
    floor_layout = QHBoxLayout(floor_row)
    floor_layout.setContentsMargins(0, 0, 0, 0)
    floor_layout.setSpacing(8)
    floor_layout.addWidget(form.floor_min)
    floor_layout.addWidget(QLabel(_TR("to")))
    floor_layout.addWidget(form.floor_max)
    form.floor_row_widget = floor_row
    form.floor_label = QLabel(_TR("Floor"))

    form.elevator = QCheckBox(_TR("Requires Elevator"))
    form.elevator.setObjectName("demandeElevatorCheck")
    form.elevator.stateChanged.connect(form._emit_changed)
    form.elevator.setAccessibleName(_TR("Requires elevator"))

    form.accessibility_required = QCheckBox(_TR("Accessibility ♿"))
    form.accessibility_required.setObjectName("demandeAccessibilityCheck")
    form.accessibility_required.stateChanged.connect(form._emit_changed)
    form.accessibility_required.setAccessibleName(_TR("Accessibility required"))

    form.tags = QLineEdit()
    form.tags.setObjectName("demandeTagsInput")
    form.tags.setPlaceholderText(_TR("e.g. parking, balcony, quiet"))
    form.tags.textChanged.connect(form._emit_changed)
    form.tags.setAccessibleName(_TR("Tags"))

    form.remarks = QLineEdit()
    form.remarks.setObjectName("demandeRemarksInput")
    form.remarks.setPlaceholderText(_TR("Notes..."))
    form.remarks.textChanged.connect(form._emit_changed)
    form.remarks.setAccessibleName(_TR("Notes"))

    identity_box, identity_grid = build_form_section(form, _TR("What the client wants"))
    identity_grid.addWidget(QLabel(_TR("Type")), 0, 0)
    identity_grid.addWidget(form.type, 0, 1)
    identity_grid.addWidget(QLabel(_TR("Looking for")), 0, 2)
    identity_grid.addWidget(form.action, 0, 3)
    identity_grid.addWidget(QLabel(_TR("City")), 1, 0)
    identity_grid.addWidget(form.wilaya, 1, 1)
    identity_grid.addWidget(QLabel(_TR("Areas")), 1, 2)
    identity_grid.addWidget(form.location, 1, 3)
    identity_grid.setColumnStretch(1, 1)
    identity_grid.setColumnStretch(3, 1)

    constraints_box, constraints_grid = build_form_section(form, _TR("Property Preferences"))
    constraints_grid.addWidget(QLabel(_TR("Bedrooms")), 0, 0)
    constraints_grid.addWidget(form.beds_min, 0, 1)
    constraints_grid.addWidget(QLabel(_TR("Furnished")), 0, 2)
    constraints_grid.addWidget(form.furnished, 0, 3)
    constraints_grid.addWidget(QLabel(_TR("Size")), 1, 0)
    constraints_grid.addWidget(surface_row, 1, 1, 1, 3)
    constraints_grid.addWidget(QLabel(_TR("Budget")), 2, 0)
    constraints_grid.addWidget(budget_row, 2, 1, 1, 3)
    constraints_grid.addWidget(form.floor_label, 3, 0)
    constraints_grid.addWidget(floor_row, 3, 1, 1, 3)
    constraints_grid.setColumnStretch(1, 1)
    constraints_grid.setColumnStretch(3, 1)

    prefs_box, prefs_grid = build_form_section(form, _TR("Accessibility & Notes"))
    prefs_grid.addWidget(form.elevator, 0, 0, 1, 2)
    prefs_grid.addWidget(form.accessibility_required, 0, 2, 1, 2)
    prefs_grid.addWidget(QLabel(_TR("Tags")), 1, 0)
    prefs_grid.addWidget(form.tags, 1, 1, 1, 3)
    prefs_grid.addWidget(QLabel(_TR("Notes")), 2, 0)
    prefs_grid.addWidget(form.remarks, 2, 1, 1, 3)
    prefs_grid.setColumnStretch(1, 1)
    prefs_grid.setColumnStretch(3, 1)

    layout.addWidget(identity_box)
    layout.addWidget(constraints_box)
    layout.addWidget(prefs_box)

    form.setTabOrder(form.type, form.action)
    form.setTabOrder(form.action, form.wilaya)
    form.setTabOrder(form.wilaya, form.location)
    form.setTabOrder(form.location, form.beds_min)
    form.setTabOrder(form.beds_min, form.surface_min)
    form.setTabOrder(form.surface_min, form.surface_max)
    form.setTabOrder(form.surface_max, form.budget_min)
    form.setTabOrder(form.budget_min, form.budget_max)
    form.setTabOrder(form.budget_max, form.furnished)
    form.setTabOrder(form.furnished, form.floor_min)
    form.setTabOrder(form.floor_min, form.floor_max)
    form.setTabOrder(form.floor_max, form.elevator)
    form.setTabOrder(form.elevator, form.accessibility_required)
    form.setTabOrder(form.accessibility_required, form.tags)
    form.setTabOrder(form.tags, form.remarks)

    form._on_type_changed(form.type.currentText())
