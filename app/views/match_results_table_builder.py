"""
Table builder for match result rows.
"""

from __future__ import annotations

from app.services.match_details import OfferMatch
from app.utils.i18n import tr_factory
from app.views.base import (
    APP,
    ORG,
    KeyItem,
    QHeaderView,
    QLabel,
    QPushButton,
    QSettings,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
    fmt_int_group,
    fmt_money_short,
)
from app.views.match_results_types import MatchResultsDeps

_TR = tr_factory("MatchResultsTable")
_COLUMN_WIDTHS_SETTING = "ui/match_table/v3/column_widths"


def _format_margin_pct(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value)}%"
    return f"{value:g}%"


def _build_negotiation_caption(offer: object) -> str:
    price_negotiable = bool(getattr(offer, "price_negotiable", False))
    flex_pct = float(getattr(offer, "price_flex_pct", 0) or 0)
    if flex_pct > 0:
        return _TR("Negotiable, {margin} margin").format(margin=_format_margin_pct(flex_pct))
    if price_negotiable:
        return _TR("Negotiable")
    return ""


def _build_negotiation_tooltip(offer: object) -> str:
    budget = getattr(offer, "budget", None)
    flex_pct = float(getattr(offer, "price_flex_pct", 0) or 0)
    if budget is None or flex_pct <= 0:
        return ""
    ratio = flex_pct / 100.0
    low = float(budget) * (1 - ratio)
    high = float(budget) * (1 + ratio)
    return _TR("Matching price range: {low} to {high} DZD").format(
        low=fmt_int_group(low),
        high=fmt_int_group(high),
    )


def build_matches_table(
    parent: QWidget | None,
    matches: list[OfferMatch],
    deps: MatchResultsDeps,
) -> QTableWidget:
    """Create a table for matches within a demande section."""
    columns = [
        _TR("Score"),
        _TR("Owner"),
        _TR("Type"),
        _TR("Action"),
        _TR("Location"),
        _TR("Beds"),
        _TR("Surface"),
        _TR("Budget"),
        _TR("Phone"),
        _TR("Position"),
    ]

    table: QTableWidget = QTableWidget(len(matches), len(columns), parent)
    table.setAccessibleName(_TR("Match results table"))
    table.setAccessibleDescription(_TR("Table of matching listings for the selected demande."))
    table.setHorizontalHeaderLabels(columns)
    table.setSortingEnabled(True)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(46)

    default_widths = {
        0: 40,
        1: 100,
        2: 65,
        3: 40,
        4: 120,
        5: 35,
        6: 55,
        7: 70,
        8: 90,
        9: 70,
    }

    settings = QSettings(ORG, APP)
    saved_widths = settings.value(_COLUMN_WIDTHS_SETTING, None)
    if isinstance(saved_widths, list):
        for col, width in enumerate(saved_widths):
            if col < table.columnCount():
                try:
                    table.setColumnWidth(col, int(width))
                except (ValueError, TypeError):
                    table.setColumnWidth(col, default_widths.get(col, 70))
    else:
        for col, width in default_widths.items():
            table.setColumnWidth(col, width)

    def save_match_table_widths(logical_index: int, old_size: int, new_size: int) -> None:
        widths = [table.columnWidth(i) for i in range(table.columnCount())]
        settings = QSettings(ORG, APP)
        settings.setValue(_COLUMN_WIDTHS_SETTING, widths)

    table.horizontalHeader().sectionResized.connect(save_match_table_widths)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

    for i, match in enumerate(matches):
        offer = match.offer
        score = match.score
        listing_id = match.listing_id

        listing = deps.get_listing_by_id(listing_id)
        owner_name = listing.family_name if listing else ""
        phone = listing.phone if listing else ""

        score_item = KeyItem(f"{score:.1f}", score)
        if score >= 7:
            score_item.setForeground(Qt.GlobalColor.green)
        elif score >= 4:
            score_item.setForeground(Qt.GlobalColor.yellow)
        else:
            score_item.setForeground(Qt.GlobalColor.gray)
        table.setItem(i, 0, score_item)

        table.setItem(i, 1, QTableWidgetItem(owner_name or "-"))
        table.setItem(i, 2, QTableWidgetItem(offer.type or ""))
        table.setItem(i, 3, QTableWidgetItem(offer.action or ""))
        table.setItem(i, 4, QTableWidgetItem(offer.location or ""))
        table.setItem(i, 5, KeyItem(str(offer.beds) if offer.beds else "-", offer.beds or 0))
        table.setItem(
            i,
            6,
            KeyItem(fmt_int_group(offer.surface) if offer.surface else "-", offer.surface or 0),
        )
        budget_text = fmt_money_short(offer.budget, "DZD") if offer.budget else "-"
        negotiation_caption = _build_negotiation_caption(offer)
        if negotiation_caption:
            budget_text += f" ({negotiation_caption})"

        budget_item = KeyItem("", offer.budget or 0)
        budget_label = QLabel(budget_text)
        budget_label.setTextFormat(Qt.TextFormat.PlainText)
        budget_label.setProperty("immoMuted", True)
        budget_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        negotiation_tooltip = _build_negotiation_tooltip(offer)
        if negotiation_tooltip:
            budget_label.setToolTip(negotiation_tooltip)

        table.setItem(i, 7, budget_item)
        table.setCellWidget(i, 7, budget_label)

        if phone:
            phone_btn = QPushButton(phone, table)
            phone_btn.setAccessibleName(_TR("Phone"))
            phone_btn.setAccessibleDescription(_TR("Open WhatsApp chat for this listing owner."))
            phone_btn.setProperty("phone", phone)
            phone_btn.setProperty("owner_name", owner_name)
            phone_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            phone_btn.setProperty("matchCellRole", "phone")
            phone_btn.clicked.connect(deps.on_phone_click)
            table.setCellWidget(i, 8, phone_btn)
        else:
            table.setItem(i, 8, QTableWidgetItem("-"))

        link = offer.link if offer.link else ""
        has_coords = offer.latitude is not None and offer.longitude is not None
        if link or has_coords:
            link_btn = QPushButton(_TR("GPS"), table)
            link_btn.setAccessibleName(_TR("Location link"))
            link_btn.setAccessibleDescription(_TR("Open listing location in browser."))
            if link:
                link_btn.setToolTip(link)
            elif has_coords:
                link_btn.setToolTip(f"{offer.latitude}, {offer.longitude}")
            link_btn.setProperty("link", link)
            if has_coords:
                link_btn.setProperty("latitude", offer.latitude)
                link_btn.setProperty("longitude", offer.longitude)
            link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            link_btn.setProperty("matchCellRole", "position")
            link_btn.clicked.connect(deps.on_position_click)
            table.setCellWidget(i, 9, link_btn)
        else:
            table.setItem(i, 9, QTableWidgetItem("-"))

    header_height = table.horizontalHeader().height()
    row_height = table.verticalHeader().defaultSectionSize()
    total_height = header_height + (len(matches) * row_height) + 4
    table.setFixedHeight(total_height)

    return table
