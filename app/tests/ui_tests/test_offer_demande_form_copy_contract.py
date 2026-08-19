from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from app.tests.ui_tests._ui_contract_helpers import read_file

pytestmark = pytest.mark.ui


def test_offer_form_uses_plain_language_labels() -> None:
    content = read_file("app/widgets/offer_form_ui.py")
    required = (
        '_TR("Property Basics")',
        '_TR("City")',
        '_TR("Areas")',
        '_TR("Location & Notes")',
        '_TR("View Map")',
        '_TR("Negotiable")',
        '_TR("Negotiation margin:")',
    )
    missing = [needle for needle in required if needle not in content]
    assert not missing, f"Missing offer form labels: {missing}"


def test_demande_form_uses_plain_language_labels() -> None:
    content = read_file("app/widgets/demande_form_ui.py")
    required = (
        '_TR("What the client wants")',
        '_TR("Property Preferences")',
        '_TR("City")',
        '_TR("Areas")',
        '_TR("Notes")',
    )
    missing = [needle for needle in required if needle not in content]
    assert not missing, f"Missing request form labels: {missing}"


def test_listing_edit_hydrates_offer_panels_with_full_offer_objects() -> None:
    from app.views.listings_v2_actions import ListingsTabActionsMixin

    source = textwrap.dedent(inspect.getsource(ListingsTabActionsMixin._edit_listing))
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_add_offer_panel"
    ]
    assert calls, "_edit_listing must hydrate persisted offers into edit panels"
    assert all(
        node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "offer"
        and not isinstance(node.args[0], ast.Dict)
        for node in calls
    )


def test_offer_panel_hydrates_offer_without_losing_round_tripped_fields(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(
        "app.widgets.offer_form.prime_locations_non_blocking",
        lambda *_args, **_kwargs: False,
    )

    from app.models import Offer
    from app.widgets.offer_panel import OfferPanel

    panel = OfferPanel()
    try:
        offer = Offer(
            id=41,
            listing_id=7,
            type="apartment",
            action="sell",
            wilaya="Algiers",
            wilaya_id=16,
            location="Hydra, Algiers - 16",
            beds=3,
            surface=90.0,
            budget=250.0,
            furnished="yes",
            floor=2,
            elevator=True,
            accessibility_supported=True,
            price_negotiable=True,
            price_flex_pct=12.0,
            latitude=36.7525,
            longitude=3.042,
            remarks="persisted offer fields",
            row_version=9,
        )

        panel.set_data(offer)
        data = panel.get_data()

        expected_round_trip_keys = {
            "type",
            "action",
            "wilaya",
            "location",
            "beds",
            "surface",
            "budget",
            "price_negotiable",
            "price_flex_pct",
            "furnished",
            "floor",
            "elevator",
            "accessibility_supported",
            "link",
            "latitude",
            "longitude",
            "remarks",
        }
        assert expected_round_trip_keys.issubset(data)
        assert data["id"] == 41
        assert data["row_version"] == 9
        assert data["wilaya"] == "Algiers - 16"
        assert data["accessibility_supported"] is True
        assert data["price_negotiable"] is True
        assert data["price_flex_pct"] == 12
        assert data["elevator"] is True
        assert data["location"] == "Hydra, Algiers - 16"
        assert data["latitude"] == "36.7525"
        assert data["longitude"] == "3.042"
        assert data["remarks"] == "persisted offer fields"
    finally:
        panel.close()
        panel.deleteLater()
        qapp.processEvents()
