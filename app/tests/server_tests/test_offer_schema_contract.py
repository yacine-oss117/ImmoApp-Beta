from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from core.models import Offer
from server.api.request_schemas_demandes_offers import (
    DemandePayloadSerializer,
    OfferPayloadSerializer,
)
from server.api.response_schemas import DemandeResponseSerializer, OfferResponseSerializer


def _valid_offer_payload() -> dict[str, object]:
    return {
        "type_id": 1,
        "action_id": 1,
        "wilaya_id": 16,
        "location": "Hydra",
        "beds": 3,
        "surface": 120.0,
        "budget": 9000000.0,
        "floor": 2,
        "price_negotiable": True,
        "price_flex_pct": 10.0,
    }


def test_offer_payload_serializer_accepts_negotiation_fields() -> None:
    serializer = OfferPayloadSerializer(data=_valid_offer_payload())

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["price_negotiable"] is True
    assert float(serializer.validated_data["price_flex_pct"]) == 10.0


def test_offer_payload_serializer_accepts_absent_coordinates_as_null() -> None:
    payload = {
        **_valid_offer_payload(),
        "latitude": None,
        "longitude": None,
    }

    serializer = OfferPayloadSerializer(data=payload)

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["latitude"] is None
    assert serializer.validated_data["longitude"] is None


def test_offer_response_serializer_exposes_negotiation_fields() -> None:
    fields = set(OfferResponseSerializer().fields.keys())

    assert "price_negotiable" in fields
    assert "price_flex_pct" in fields
    assert "status" in fields


def test_offer_response_serializer_preserves_boolean_flags() -> None:
    serializer = OfferResponseSerializer()

    assert isinstance(serializer.fields["price_negotiable"], serializers.BooleanField)
    assert isinstance(serializer.fields["elevator"], serializers.BooleanField)
    assert isinstance(serializer.fields["accessibility_supported"], serializers.BooleanField)
    assert serializer.fields["price_negotiable"].to_representation(1) is True
    assert serializer.fields["elevator"].to_representation(0) is False
    assert serializer.fields["accessibility_supported"].to_representation(None) is None


def test_offer_model_preserves_decimal_numeric_fields_from_database_rows() -> None:
    offer = Offer.from_row(
        {
            "id": 1,
            "listing_id": 2,
            "type": "apartment",
            "type_id": 1,
            "action": "sell",
            "action_id": 3,
            "wilaya": "Algiers",
            "wilaya_id": 16,
            "location": "Hydra, Algiers - 16",
            "beds": 3,
            "surface": Decimal("90.5"),
            "budget": Decimal("250000.25"),
            "furnished": "yes",
            "floor": 2,
            "elevator": 1,
            "accessibility_supported": 1,
            "price_negotiable": 1,
            "price_flex_pct": Decimal("12.5"),
            "link": "",
            "latitude": Decimal("36.7525"),
            "longitude": Decimal("3.042"),
            "remarks": "preserve numeric fields",
            "status": "available",
            "deleted_at": "",
            "created_at": "2026-04-27T00:00:00+00:00",
            "updated_at": "2026-04-27T00:00:00+00:00",
            "row_version": 4,
        }
    )

    assert offer.surface == 90.5
    assert offer.budget == 250000.25
    assert offer.price_flex_pct == 12.5
    assert offer.latitude == 36.7525
    assert offer.longitude == 3.042


def test_demande_schema_contract_preserves_range_fields() -> None:
    request_fields = set(DemandePayloadSerializer().fields.keys())
    response_fields = set(DemandeResponseSerializer().fields.keys())

    for field_name in {
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "floor_min",
        "floor_max",
    }:
        assert field_name in request_fields
        assert field_name in response_fields


def test_demande_payload_serializer_accepts_partial_range_preferences() -> None:
    serializer = DemandePayloadSerializer(
        data={
            "type_id": 1,
            "action_id": 1,
            "wilaya_id": 16,
            "budget_max": 1500000.0,
            "surface_min": 80.0,
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["budget_max"] == 1500000.0
    assert serializer.validated_data["surface_min"] == 80.0
    assert "budget_min" not in serializer.validated_data
    assert "surface_max" not in serializer.validated_data


def test_demande_response_serializer_preserves_boolean_flags() -> None:
    serializer = DemandeResponseSerializer()

    assert isinstance(serializer.fields["elevator"], serializers.BooleanField)
    assert isinstance(serializer.fields["accessibility_required"], serializers.BooleanField)
    assert serializer.fields["elevator"].to_representation(1) is True
    assert serializer.fields["accessibility_required"].to_representation(0) is False


def test_offer_label_update_drops_stale_lookup_id_for_resolution() -> None:
    from server.services.offers import _drop_stale_lookup_ids

    processed = {
        "type": "house",
        "type_id": 1,
        "action": "sell",
        "action_id": 3,
        "wilaya": "Algiers - 16",
        "wilaya_id": 16,
    }

    _drop_stale_lookup_ids(processed, {"type": "house", "type_id": 1})

    assert processed["type_id"] is None
    assert processed["action_id"] == 3
    assert processed["wilaya_id"] == 16


def test_demande_label_update_drops_stale_lookup_id_for_resolution() -> None:
    from server.services.demandes import _drop_stale_lookup_ids

    processed = {
        "type": "house",
        "type_id": 1,
        "action": "buy",
        "action_id": 1,
        "wilaya": "Algiers - 16",
        "wilaya_id": 16,
    }

    _drop_stale_lookup_ids(processed, {"type": "house", "type_id": 1})

    assert processed["type_id"] is None
    assert processed["action_id"] == 1
    assert processed["wilaya_id"] == 16
