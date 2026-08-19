from __future__ import annotations

import pytest

from app.models import Listing, Offer
from app.services.match_details import OfferMatch
from app.views.base import QLabel, QWidget
from app.views.match_results_table_builder import build_matches_table
from app.views.match_results_types import MatchResultsDeps

pytestmark = pytest.mark.ui


def _deps() -> MatchResultsDeps:
    listing = Listing(id=7, family_name="Owner Name", phone="0555123456")
    return MatchResultsDeps(
        get_listing_by_id=lambda _listing_id: listing,
        create_action_buttons=lambda _listing_id, _offer, parent=None: QWidget(parent),
        on_phone_click=lambda: None,
        on_position_click=lambda: None,
        on_load_more=lambda: None,
        on_show_all=lambda: None,
        allow_pagination=False,
    )


def test_budget_cell_shows_negotiation_margin_and_range_tooltip(qapp) -> None:
    parent = QWidget()
    offer = Offer(
        id=5,
        listing_id=7,
        type="apartment",
        action="sell",
        location="Hydra",
        budget=10_000_000,
        surface=120.0,
        beds=3,
        floor=2,
        price_negotiable=True,
        price_flex_pct=10.0,
        status="available",
    )
    table = build_matches_table(
        parent=parent,
        matches=[OfferMatch(listing_id=7, offer=offer, score=8.2)],
        deps=_deps(),
    )

    budget_label = table.cellWidget(0, 7)
    assert isinstance(budget_label, QLabel)
    assert "Negotiable, 10% margin" in budget_label.text()
    assert "9 000 000" in budget_label.toolTip()
    assert "11 000 000" in budget_label.toolTip()


def test_budget_cell_shows_plain_negotiable_without_margin(qapp) -> None:
    parent = QWidget()
    offer = Offer(
        id=6,
        listing_id=7,
        type="apartment",
        action="sell",
        location="Hydra",
        budget=10_000_000,
        surface=120.0,
        beds=3,
        floor=2,
        price_negotiable=True,
        price_flex_pct=0.0,
        status="available",
    )
    table = build_matches_table(
        parent=parent,
        matches=[OfferMatch(listing_id=7, offer=offer, score=8.2)],
        deps=_deps(),
    )

    budget_label = table.cellWidget(0, 7)
    assert isinstance(budget_label, QLabel)
    assert "Negotiable" in budget_label.text()
    assert "margin" not in budget_label.text().lower()
    assert budget_label.toolTip() == ""
