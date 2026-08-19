"""UI builder for the simulation dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("SimulationDialog")

if TYPE_CHECKING:
    from app.views.dialogs.simulation_dialog import SimulationDialog


def setup_simulation_dialog_ui(dialog: SimulationDialog) -> None:
    """Build UI controls and attach them to the dialog."""
    dialog.setWindowTitle(_TR("Estimate"))
    dialog.setMinimumWidth(540)
    dialog.setModal(True)
    dialog.setObjectName("immoDialog")

    layout = QVBoxLayout(dialog)
    layout.setSpacing(16)

    title = QLabel(_TR("Estimate"))
    title.setObjectName("dialogSectionTitle")
    title_font = QFont()
    title_font.setPointSize(16)
    title_font.setWeight(QFont.Weight.Bold)
    title.setFont(title_font)
    layout.addWidget(title)

    dialog._status_banner = QLabel(_TR("No simulation active"))
    dialog._status_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
    dialog._status_banner.setObjectName("simulationStatusBanner")
    layout.addWidget(dialog._status_banner)

    status_group = QGroupBox(_TR("Estimate Status"))
    status_group.setProperty("immoCard", True)
    status_group.setProperty("immoRole", "dialogPanel")
    status_layout = QVBoxLayout(status_group)
    dialog._status_text = QLabel(_TR("Ready for simulation."))
    dialog._status_text.setWordWrap(True)
    dialog._counts_text = QLabel(_TR("Counts: -"))
    dialog._counts_text.setProperty("immoState", "muted")
    status_layout.addWidget(dialog._status_text)
    status_layout.addWidget(dialog._counts_text)
    layout.addWidget(status_group)

    seed_group = QGroupBox(_TR("Estimate Options"))
    seed_group.setProperty("immoCard", True)
    seed_group.setProperty("immoRole", "dialogPanel")
    seed_layout = QFormLayout(seed_group)
    dialog._client_count = _spin_box(10, 2000, 30)
    dialog._listing_count = _spin_box(10, 2000, 30)
    dialog._demandes_per_client = _spin_box(1, 5, 1)
    dialog._offers_per_listing = _spin_box(1, 5, 1)
    seed_layout.addRow(_TR("Clients:"), dialog._client_count)
    seed_layout.addRow(_TR("Properties:"), dialog._listing_count)
    seed_layout.addRow(_TR("Requests per client:"), dialog._demandes_per_client)
    seed_layout.addRow(_TR("Offers per listing:"), dialog._offers_per_listing)
    layout.addWidget(seed_group)

    note = QLabel(
        _TR(
            "Estimate data stays separate from your live data and follows the same "
            "business rules."
        )
    )
    note.setWordWrap(True)
    note.setProperty("immoState", "muted")
    note.setObjectName("simulationDialogNote")
    layout.addWidget(note)

    action_layout = QHBoxLayout()
    dialog._start_seed_btn = QPushButton(_TR("Start Simulation (Seed)"))
    dialog._start_clone_btn = QPushButton(_TR("Clone Real Data"))
    dialog._save_btn = QPushButton(_TR("Save Simulation to Real"))
    dialog._delete_btn = QPushButton(_TR("Delete Simulation"))
    dialog._close_btn = QPushButton(_TR("Close"))
    dialog._start_seed_btn.setProperty("immoVariant", "primary")
    dialog._start_clone_btn.setProperty("immoVariant", "warning")
    dialog._save_btn.setProperty("immoVariant", "danger")
    dialog._delete_btn.setProperty("immoVariant", "warning")
    dialog._close_btn.setProperty("immoVariant", "ghost")

    action_layout.addWidget(dialog._start_seed_btn)
    action_layout.addWidget(dialog._start_clone_btn)
    action_layout.addWidget(dialog._save_btn)
    action_layout.addWidget(dialog._delete_btn)
    action_layout.addStretch()
    action_layout.addWidget(dialog._close_btn)
    layout.addLayout(action_layout)


def _spin_box(min_value: int, max_value: int, default: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(min_value, max_value)
    box.setValue(default)
    return box
