from __future__ import annotations

from app.views.imports.import_experience import ENTITY_FIELD_ORDER
from app.views.imports.mapping_field_contract import (
    CLIENT_FIELD_KEYS,
    DEMANDE_FIELD_KEYS,
    LISTING_FIELD_KEYS,
    OFFER_FIELD_KEYS,
)
from server.api.request_schemas_clients import ClientPayloadSerializer, ListingPayloadSerializer
from server.api.request_schemas_demandes_offers import (
    DemandePayloadSerializer,
    OfferPayloadSerializer,
)
from server.api.response_schemas import (
    ClientResponseSerializer,
    DemandeResponseSerializer,
    ListingResponseSerializer,
    OfferResponseSerializer,
)


def test_import_mapping_fields_match_public_entity_contracts() -> None:
    client_request = set(ClientPayloadSerializer().fields.keys())
    client_response = set(ClientResponseSerializer().fields.keys())
    assert set(CLIENT_FIELD_KEYS).issubset(client_request | client_response)

    listing_request = set(ListingPayloadSerializer().fields.keys())
    listing_response = set(ListingResponseSerializer().fields.keys())
    assert set(LISTING_FIELD_KEYS).issubset(listing_request | listing_response)

    demande_request = set(DemandePayloadSerializer().fields.keys())
    demande_response = set(DemandeResponseSerializer().fields.keys())
    demande_allowed_extras = {"client_id"}
    assert set(DEMANDE_FIELD_KEYS).issubset(
        demande_request | demande_response | demande_allowed_extras
    )

    offer_request = set(OfferPayloadSerializer().fields.keys())
    offer_response = set(OfferResponseSerializer().fields.keys())
    offer_allowed_extras = {"listing_id"}
    assert set(OFFER_FIELD_KEYS).issubset(offer_request | offer_response | offer_allowed_extras)


def test_import_summary_field_order_stays_within_entity_contracts() -> None:
    client_contract = set(ClientPayloadSerializer().fields.keys()) | set(
        ClientResponseSerializer().fields.keys()
    )
    listing_contract = set(ListingPayloadSerializer().fields.keys()) | set(
        ListingResponseSerializer().fields.keys()
    )
    demande_contract = set(DemandePayloadSerializer().fields.keys()) | set(
        DemandeResponseSerializer().fields.keys()
    )
    offer_contract = set(OfferPayloadSerializer().fields.keys()) | set(
        OfferResponseSerializer().fields.keys()
    )

    assert set(ENTITY_FIELD_ORDER["client"]).issubset(client_contract)
    assert set(ENTITY_FIELD_ORDER["listing"]).issubset(listing_contract)
    assert set(ENTITY_FIELD_ORDER["demande"]).issubset(demande_contract)
    assert set(ENTITY_FIELD_ORDER["offer"]).issubset(offer_contract)
