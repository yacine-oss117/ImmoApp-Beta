"""
Unit tests for trash dialog render helpers.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.models import Client, Contract, Demande, Listing, Offer, Visit  # noqa: E402
from app.utils.time_humanize import humanize_relative  # noqa: E402
from app.views.dialogs.trash_dialog import TrashDialog  # noqa: E402

pytestmark = pytest.mark.ui


def test_render_client_row() -> None:
    client = Client(id=1, family_name="A", phone="123", deleted_at="2024-01-01")
    assert TrashDialog._render_client(client) == [
        "1",
        "A",
        "123",
        humanize_relative("2024-01-01"),
    ]


def test_render_listing_row() -> None:
    listing = Listing(id=2, family_name="Owner", phone="555", deleted_at="2024")
    assert TrashDialog._render_listing(listing) == [
        "2",
        "Owner",
        "555",
        humanize_relative("2024"),
    ]


def test_render_demande_row() -> None:
    demande = Demande(
        id=3,
        client_id=7,
        type="apartment",
        action="buy",
        locations="Bab Ezzouar",
        deleted_at="2024-02-01",
    )
    assert TrashDialog._render_demande(demande) == [
        "3",
        "7",
        "apartment",
        "buy",
        "Bab Ezzouar",
        humanize_relative("2024-02-01"),
    ]


def test_render_offer_row() -> None:
    offer = Offer(
        id=4,
        listing_id=9,
        type="apartment",
        action="sell",
        location="Alger",
        deleted_at="2024-02-02",
    )
    assert TrashDialog._render_offer(offer) == [
        "4",
        "9",
        "apartment",
        "sell",
        "Alger",
        humanize_relative("2024-02-02"),
    ]


def test_render_visit_row() -> None:
    visit = Visit(
        id=5,
        client_id=10,
        listing_id=11,
        scheduled_date="2024-03-01",
        status="scheduled",
        deleted_at="2024-03-05",
    )
    assert TrashDialog._render_visit(visit) == [
        "5",
        "10",
        "11",
        humanize_relative("2024-03-01"),
        "scheduled",
        humanize_relative("2024-03-05"),
    ]


def test_render_contract_row() -> None:
    contract = Contract(
        id=6,
        client_id=12,
        listing_id=13,
        status="draft",
        deleted_at="2024-04-01",
    )
    assert TrashDialog._render_contract(contract) == [
        "6",
        "12",
        "13",
        "draft",
        humanize_relative("2024-04-01"),
    ]
