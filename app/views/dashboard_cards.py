"""
Dashboard card factories.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.utils.i18n import tr_factory

_TR = tr_factory("DashboardCards")


def _base_card(parent: QWidget, role: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame(parent)
    card.setProperty("immoCard", True)
    card.setProperty("cardRole", role)
    layout = QVBoxLayout(card)
    layout.setSpacing(8)
    layout.setContentsMargins(12, 12, 12, 12)
    return card, layout


def create_visit_card_from_dict(parent: QWidget, visit: dict[str, object]) -> QFrame:
    """Create visit card from cached dict data."""
    card, layout = _base_card(parent, "visit")
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    scheduled = str(visit.get("scheduled_time") or "")
    time_lbl = QLabel(scheduled[:5], card)
    time_lbl.setProperty("leadTitle", True)
    row.addWidget(time_lbl)

    info = QVBoxLayout()
    client_name = visit.get("client_name")
    title_text = str(client_name) if client_name else _TR("Client")
    title = QLabel(title_text, card)
    title.setProperty("leadTitle", True)
    listing_loc = visit.get("listing_location")
    location_label = str(listing_loc) if listing_loc else _TR("Unknown location")
    subtitle = QLabel(location_label, card)
    subtitle.setProperty("immoMuted", True)
    info.addWidget(title)
    info.addWidget(subtitle)
    row.addLayout(info)
    row.addStretch()

    layout.addLayout(row)
    return card


def create_contract_card_from_dict(parent: QWidget, contract: dict[str, object]) -> QFrame:
    """Create expiring contract card from cached dict data."""
    card, layout = _base_card(parent, "contract")
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    info = QVBoxLayout()

    client_name = contract.get("client_name")
    title_text = str(client_name) if client_name else _TR("Client")
    title = QLabel(title_text, card)
    title.setProperty("leadTitle", True)
    listing_loc = str(contract.get("listing_location") or "")
    end_date = str(contract.get("end_date") or _TR("N/A"))
    location_label = listing_loc or _TR("Unknown location")
    subtitle = QLabel(
        _TR("{location} - Expires: {date}").format(location=location_label, date=end_date),
        card,
    )
    subtitle.setProperty("immoMuted", True)

    info.addWidget(title)
    info.addWidget(subtitle)
    row.addLayout(info)
    row.addStretch()
    layout.addLayout(row)
    return card


def create_pending_contract_card_from_dict(parent: QWidget, contract: dict[str, object]) -> QFrame:
    """Create pending signature contract card from cached dict data."""
    card, layout = _base_card(parent, "pending")
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    info = QVBoxLayout()

    client_name = contract.get("client_name")
    title_text = str(client_name) if client_name else _TR("Client")
    title = QLabel(title_text, card)
    title.setProperty("leadTitle", True)
    listing_loc = str(contract.get("listing_location") or "")
    contract_type = str(contract.get("contract_type") or "").strip().lower()
    type_label = {
        "rent": _TR("Rent"),
        "buy": _TR("Buy"),
        "sell": _TR("Sell"),
    }.get(contract_type, contract_type or _TR("N/A"))
    location_label = listing_loc or _TR("Unknown location")
    subtitle = QLabel(
        _TR("{location} - {type}").format(location=location_label, type=type_label),
        card,
    )
    subtitle.setProperty("immoMuted", True)

    info.addWidget(title)
    info.addWidget(subtitle)
    row.addLayout(info)
    row.addStretch()

    date_str = str(contract.get("created_at") or "")[:10] or _TR("N/A")
    date_lbl = QLabel(date_str, card)
    date_lbl.setProperty("immoMuted", True)
    row.addWidget(date_lbl)

    layout.addLayout(row)
    return card


def create_lead_card_from_dict(
    parent: QWidget,
    lead: dict[str, object],
    on_click: Callable[[], None],
) -> QFrame:
    """Create a hot lead card, with a view button callback."""
    card, layout = _base_card(parent, "lead")
    card.setCursor(Qt.CursorShape.PointingHandCursor)

    top_row = QHBoxLayout()
    family_name = lead.get("family_name")
    name = str(family_name) if family_name else _TR("Client")
    name_label = QLabel(_TR("Client: {name}").format(name=name), card)
    name_label.setProperty("leadTitle", True)
    top_row.addWidget(name_label)
    top_row.addStretch()

    count_obj = lead.get("count", 0)
    count = count_obj if isinstance(count_obj, int) else 0
    badge = QLabel(_TR("{count} Matches").format(count=count), card)
    badge.setProperty("leadBadge", True)
    top_row.addWidget(badge)
    layout.addLayout(top_row)

    bottom_row = QHBoxLayout()
    bottom_row.setContentsMargins(0, 4, 0, 0)

    phone_obj = lead.get("phone")
    phone = str(phone_obj) if phone_obj else _TR("No phone")
    phone_label = QLabel(_TR("Phone: {phone}").format(phone=phone), card)
    phone_label.setProperty("immoMuted", True)
    bottom_row.addWidget(phone_label)
    bottom_row.addStretch()

    view_btn = QPushButton(_TR("View Client"), card)
    view_btn.setAccessibleName(_TR("View client"))
    view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    view_btn.setProperty("immoVariant", "secondary")
    view_btn.clicked.connect(on_click)
    bottom_row.addWidget(view_btn)

    layout.addLayout(bottom_row)
    return card
