"""
Match tab UI builder helpers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from app.utils.i18n import tr_factory
from app.views.base import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    Qt,
    QVBoxLayout,
    QWidget,
    SearchableComboBox,
)
from app.views.match_state import load_match_settings
from app.widgets.notice_banner import NoticeBanner

logger = logging.getLogger(__name__)
_TR = tr_factory("MatchUi")


@dataclass(frozen=True)
class MatchUiWidgets:
    """Container for Match tab widgets."""

    notice_banner: NoticeBanner
    client_select: SearchableComboBox
    min_matches: QSpinBox
    threshold: QDoubleSpinBox
    limit: QSpinBox
    run_btn: QPushButton
    progress_label: QLabel
    results_container: QWidget
    results_layout: QVBoxLayout
    scroll_area: QScrollArea
    placeholder: QLabel
    controls_card: QFrame
    results_card: QFrame


def build_match_ui(
    *,
    parent: QWidget,
    on_client_search: Callable[[str], None],
    on_filter_changed: Callable[[], None],
    on_run_match: Callable[[], None],
    on_save_settings: Callable[[], None],
) -> MatchUiWidgets:
    """Build the Match tab UI and attach it to the parent widget."""
    client_select = SearchableComboBox(parent)
    client_select.setObjectName("matchClientSelect")
    client_select.setMinimumWidth(300)
    client_select.setAccessibleName(_TR("Client selector"))
    client_select.setAccessibleDescription(_TR("Search and select a client to run matching."))

    try:
        client_edit = cast(QLineEdit, client_select.lineEdit())
        client_edit.textEdited.disconnect()
    except (RuntimeError, TypeError):
        logger.debug("Failed to disconnect textEdited signal", exc_info=True)

    client_edit = cast(QLineEdit, client_select.lineEdit())
    client_edit.textEdited.connect(on_client_search)

    min_matches = QSpinBox(parent)
    min_matches.setObjectName("matchMinMatches")
    min_matches.setRange(0, 999999)
    min_matches.setValue(0)
    min_matches.setToolTip(_TR("Filter clients by minimum match count (0 = show all)"))
    min_matches.setAccessibleName(_TR("Minimum matches"))
    min_matches.setAccessibleDescription(_TR("Minimum matches filter for the client list."))

    threshold = QDoubleSpinBox(parent)
    threshold.setObjectName("matchScoreThreshold")
    threshold.setRange(0, 10)
    threshold.setDecimals(1)
    threshold.setValue(0.0)
    threshold.setToolTip(_TR("Minimum match score (0-10)"))
    threshold.setAccessibleName(_TR("Score threshold"))
    threshold.setAccessibleDescription(_TR("Minimum score required for match results."))

    limit = QSpinBox(parent)
    limit.setObjectName("matchResultLimit")
    limit.setRange(1, 200)
    limit.setValue(20)
    limit.setToolTip(_TR("Maximum matches per demande"))
    limit.setAccessibleName(_TR("Maximum matches per demande"))
    limit.setAccessibleDescription(_TR("Maximum number of matches per demande."))

    run_btn = QPushButton(_TR("Find matches"), parent)
    run_btn.setObjectName("matchRunButton")
    run_btn.setShortcut("Return")
    run_btn.setProperty("immoVariant", "primary")
    run_btn.setProperty("immoSize", "md")
    run_btn.setAccessibleName(_TR("Run match"))
    run_btn.setMinimumWidth(180)

    progress_label = QLabel("", parent)
    progress_label.setObjectName("matchProgressLabel")
    progress_label.setProperty("immoState", "muted")
    progress_label.hide()
    progress_label.setAccessibleName(_TR("Match progress"))

    results_container = QWidget(parent)
    results_container.setObjectName("matchResultsContainer")
    results_container.setAccessibleName(_TR("Match results list"))
    results_container.setAccessibleDescription(_TR("List of match result cards."))
    results_layout = QVBoxLayout(results_container)
    results_layout.setContentsMargins(0, 0, 0, 0)
    results_layout.setSpacing(8)
    results_layout.addStretch()

    scroll_area = QScrollArea(parent)
    scroll_area.setObjectName("matchResultsScrollArea")
    scroll_area.setWidgetResizable(True)
    scroll_area.setWidget(results_container)
    scroll_area.setFrameShape(QFrame.Shape.NoFrame)
    scroll_area.setMinimumHeight(240)
    scroll_area.setAccessibleName(_TR("Match results"))
    scroll_area.setAccessibleDescription(_TR("Scrollable list of match results."))

    placeholder = QLabel(_TR("Select a client and click 'Find matches' to see results"), parent)
    placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
    placeholder.setObjectName("matchPlaceholder")
    placeholder.setAccessibleName(_TR("Match results empty state"))
    placeholder.setAccessibleDescription(
        _TR("Empty-state hint for running matches after selecting a client.")
    )
    placeholder.setProperty("immoCard", True)
    placeholder.setContentsMargins(20, 20, 20, 20)

    settings = load_match_settings()
    threshold.setValue(settings.score_threshold)
    limit.setValue(settings.limit_per_demande)
    min_matches.setValue(settings.min_matches)

    min_matches.valueChanged.connect(on_filter_changed)
    threshold.valueChanged.connect(on_save_settings)
    limit.valueChanged.connect(on_save_settings)
    run_btn.clicked.connect(on_run_match)

    notice_banner = NoticeBanner(parent)

    form = QFormLayout()
    form.setSpacing(10)
    form.addRow(_TR("Client"), client_select)
    form.addRow(_TR("Minimum matches"), min_matches)
    form.addRow(_TR("Score threshold"), threshold)
    form.addRow(_TR("Max results per request"), limit)
    form.addRow("", run_btn)
    form.addRow("", progress_label)

    controls_card = QFrame(parent)
    controls_card.setObjectName("matchControlsCard")
    controls_card.setProperty("immoCard", True)
    controls_card.setProperty("immoRole", "matchControls")
    controls_card.setMinimumWidth(300)
    controls_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    controls_layout = QVBoxLayout(controls_card)
    controls_layout.setContentsMargins(12, 12, 12, 12)
    controls_layout.setSpacing(10)
    controls_layout.addLayout(form)

    results_card = QFrame(parent)
    results_card.setObjectName("matchResultsCard")
    results_card.setProperty("immoCard", True)
    results_card.setProperty("immoRole", "matchResults")
    results_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    results_layout_wrap = QVBoxLayout(results_card)
    results_layout_wrap.setContentsMargins(12, 12, 12, 12)
    results_layout_wrap.setSpacing(10)
    results_layout_wrap.addWidget(placeholder)
    results_layout_wrap.addWidget(scroll_area)

    workspace_layout = QHBoxLayout()
    workspace_layout.setContentsMargins(0, 0, 0, 0)
    workspace_layout.setSpacing(10)
    workspace_layout.addWidget(controls_card, 0)
    workspace_layout.addWidget(results_card, 1)

    layout = QVBoxLayout()
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(10)
    layout.addWidget(notice_banner)
    layout.addLayout(workspace_layout, 1)

    scroll_area.hide()
    parent.setLayout(layout)
    parent.setTabOrder(client_select, min_matches)
    parent.setTabOrder(min_matches, threshold)
    parent.setTabOrder(threshold, limit)
    parent.setTabOrder(limit, run_btn)

    return MatchUiWidgets(
        notice_banner=notice_banner,
        client_select=client_select,
        min_matches=min_matches,
        threshold=threshold,
        limit=limit,
        run_btn=run_btn,
        progress_label=progress_label,
        results_container=results_container,
        results_layout=results_layout,
        scroll_area=scroll_area,
        placeholder=placeholder,
        controls_card=controls_card,
        results_card=results_card,
    )
