"""
Dashboard UI builder.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.utils.i18n import tr_factory

_TR = tr_factory("DashboardUi")


@dataclass(frozen=True)
class DashboardUi:
    """Primary widgets for the dashboard view."""

    notice_banner: QLabel
    next_steps_card: QFrame
    next_steps_hint: QLabel
    next_steps_clients_btn: QPushButton
    next_steps_properties_btn: QPushButton
    next_steps_matches_btn: QPushButton
    next_steps_hide_btn: QPushButton
    stat_clients: QLabel
    stat_listings: QLabel
    stat_visits: QLabel
    stat_contracts: QLabel
    pending_container: QVBoxLayout
    visits_container: QVBoxLayout
    contracts_container: QVBoxLayout
    leads_container: QVBoxLayout
    refresh_button: QPushButton


def build_dashboard_ui(
    parent: QWidget,
    on_refresh: Callable[[], None],
    *,
    on_open_clients: Callable[[], None],
    on_open_properties: Callable[[], None],
    on_open_matches: Callable[[], None],
    on_hide_next_steps: Callable[[], None],
) -> DashboardUi:
    """Build the dashboard layout and return key widgets."""
    main_layout = QVBoxLayout(parent)
    main_layout.setSpacing(20)
    main_layout.setContentsMargins(20, 20, 20, 20)

    header = QLabel(_TR("Dashboard"))
    header.setAccessibleName(_TR("Dashboard header"))
    header.setObjectName("dashboardTitle")
    header.setAlignment(Qt.AlignmentFlag.AlignCenter)
    main_layout.addWidget(header)

    notice_banner = QLabel("")
    notice_banner.setAccessibleName(_TR("Dashboard notice"))
    notice_banner.setAccessibleDescription(_TR("Status banner for dashboard alerts."))
    notice_banner.setWordWrap(True)
    notice_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
    notice_banner.setObjectName("dashboardNotice")
    notice_banner.setProperty("immoCard", True)
    notice_banner.setVisible(False)
    main_layout.addWidget(notice_banner)

    next_steps_card = QFrame(parent)
    next_steps_card.setProperty("immoCard", True)
    next_steps_card.setObjectName("dashboardNextStepsCard")
    next_steps_layout = QVBoxLayout(next_steps_card)
    next_steps_layout.setContentsMargins(14, 12, 14, 12)
    next_steps_layout.setSpacing(10)

    next_steps_title = QLabel(_TR("What to do next"), next_steps_card)
    next_steps_title.setObjectName("dashboardSectionTitle")
    next_steps_layout.addWidget(next_steps_title)

    next_steps_hint = QLabel(
        _TR("Start by adding a client, then add a property, then run matching."),
        next_steps_card,
    )
    next_steps_hint.setWordWrap(True)
    next_steps_hint.setProperty("immoState", "muted")
    next_steps_layout.addWidget(next_steps_hint)

    next_steps_actions = QHBoxLayout()
    next_steps_actions.setSpacing(8)

    next_steps_clients_btn = QPushButton(_TR("Add Client"), next_steps_card)
    next_steps_clients_btn.setProperty("immoVariant", "primary")
    next_steps_clients_btn.clicked.connect(on_open_clients)
    next_steps_actions.addWidget(next_steps_clients_btn)

    next_steps_properties_btn = QPushButton(_TR("Add Property"), next_steps_card)
    next_steps_properties_btn.setProperty("immoVariant", "secondary")
    next_steps_properties_btn.clicked.connect(on_open_properties)
    next_steps_actions.addWidget(next_steps_properties_btn)

    next_steps_matches_btn = QPushButton(_TR("Find Matches"), next_steps_card)
    next_steps_matches_btn.setProperty("immoVariant", "secondary")
    next_steps_matches_btn.clicked.connect(on_open_matches)
    next_steps_actions.addWidget(next_steps_matches_btn)

    next_steps_hide_btn = QPushButton(_TR("Hide tips"), next_steps_card)
    next_steps_hide_btn.setProperty("immoVariant", "ghost")
    next_steps_hide_btn.clicked.connect(on_hide_next_steps)
    next_steps_actions.addWidget(next_steps_hide_btn)

    next_steps_actions.addStretch()
    next_steps_layout.addLayout(next_steps_actions)
    next_steps_card.setVisible(False)
    main_layout.addWidget(next_steps_card)

    stats_frame, stat_labels = _build_stats_row(parent)
    main_layout.addWidget(stats_frame)

    content_layout = QHBoxLayout()
    content_layout.setSpacing(20)

    pending_container = QVBoxLayout()
    visits_container = QVBoxLayout()
    contracts_container = QVBoxLayout()
    leads_container = QVBoxLayout()

    left_col = QVBoxLayout()
    left_col.addWidget(_create_section_header(_TR("Pending contracts")))
    left_col.addLayout(pending_container)
    left_col.addSpacing(20)
    left_col.addWidget(_create_section_header(_TR("Today's visits")))
    left_col.addLayout(visits_container)
    left_col.addStretch()

    left_frame = QFrame(parent)
    left_frame.setProperty("immoCard", True)
    left_frame.setLayout(left_col)
    content_layout.addWidget(left_frame, 1)

    right_col = QVBoxLayout()
    right_col.addWidget(_create_section_header(_TR("Contracts ending soon")))
    right_col.addLayout(contracts_container)
    right_col.addSpacing(20)
    right_col.addWidget(_create_section_header(_TR("Top opportunities")))
    right_col.addLayout(leads_container)
    right_col.addStretch()

    right_frame = QFrame(parent)
    right_frame.setProperty("immoCard", True)
    right_frame.setLayout(right_col)
    content_layout.addWidget(right_frame, 1)

    main_layout.addLayout(content_layout, 1)

    refresh_button = QPushButton(_TR("Refresh dashboard"))
    refresh_button.clicked.connect(on_refresh)
    refresh_button.setAccessibleName(_TR("Refresh dashboard"))
    refresh_button.setProperty("immoVariant", "primary")
    main_layout.addWidget(refresh_button, alignment=Qt.AlignmentFlag.AlignCenter)

    return DashboardUi(
        notice_banner=notice_banner,
        next_steps_card=next_steps_card,
        next_steps_hint=next_steps_hint,
        next_steps_clients_btn=next_steps_clients_btn,
        next_steps_properties_btn=next_steps_properties_btn,
        next_steps_matches_btn=next_steps_matches_btn,
        next_steps_hide_btn=next_steps_hide_btn,
        stat_clients=stat_labels.clients,
        stat_listings=stat_labels.listings,
        stat_visits=stat_labels.visits,
        stat_contracts=stat_labels.contracts,
        pending_container=pending_container,
        visits_container=visits_container,
        contracts_container=contracts_container,
        leads_container=leads_container,
        refresh_button=refresh_button,
    )


@dataclass(frozen=True)
class _StatLabels:
    """Container for dashboard stat labels."""

    clients: QLabel
    listings: QLabel
    visits: QLabel
    contracts: QLabel


def _build_stats_row(parent: QWidget) -> tuple[QFrame, _StatLabels]:
    frame = QFrame(parent)
    layout = QHBoxLayout(frame)
    layout.setSpacing(15)

    card_clients, stat_clients = _create_stat_card(parent, _TR("Clients"))
    card_listings, stat_listings = _create_stat_card(parent, _TR("Properties"))
    card_visits, stat_visits = _create_stat_card(parent, _TR("Visits"))
    card_contracts, stat_contracts = _create_stat_card(parent, _TR("Contracts"))

    layout.addWidget(card_clients)
    layout.addWidget(card_listings)
    layout.addWidget(card_visits)
    layout.addWidget(card_contracts)

    return frame, _StatLabels(
        clients=stat_clients,
        listings=stat_listings,
        visits=stat_visits,
        contracts=stat_contracts,
    )


def _create_stat_card(parent: QWidget, title: str) -> tuple[QFrame, QLabel]:
    card = QFrame(parent)
    card.setProperty("immoCard", True)

    layout = QVBoxLayout(card)
    layout.setSpacing(5)

    title_label = QLabel(title, card)
    title_label.setAccessibleName(_TR("Stat label"))
    title_label.setObjectName("dashboardStatTitle")

    value_label = QLabel("0", card)
    value_label.setAccessibleName(_TR("Stat value"))
    value_label.setAccessibleDescription(_TR("Current value for {title}.").format(title=title))
    value_label.setObjectName("dashboardStatValue")
    value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(value_label, alignment=Qt.AlignmentFlag.AlignCenter)

    return card, value_label


def _create_section_header(text: str) -> QLabel:
    label = QLabel(text)
    label.setAccessibleName(text)
    label.setObjectName("dashboardSectionTitle")
    return label
