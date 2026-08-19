"""
Strict TypedDict definitions for core entity inputs.
Used to enforce strong typing across the repository and API layers.
"""

from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired

# Type aliases for entity IDs
ClientId = int
DemandeId = int
OfferId = int
ListingId = int


class ClientInput(TypedDict, total=False):
    """Payload for creating or updating a client."""

    id: int
    family_name: str
    phone: str
    remarks: str
    tags: str
    is_vip: int
    status: str
    created_at: str | None
    created_loc: str
    updated_at: str | None
    row_version: int
    agency_id: int
    family_name_enc: str
    family_name_search_src: str | None
    phone_enc: str
    phone_search_src: str | None
    remarks_enc: str


class DemandeInput(TypedDict, total=False):
    """Payload for creating or updating a demande."""

    id: int
    client_id: int
    type_id: int | None
    action_id: int | None
    wilaya_id: int | None
    budget_min: float | None
    budget_max: float | None
    surface_min: float | None
    surface_max: float | None
    beds_min: int | None
    floor_min: int | None
    floor_max: int | None
    furnished: str
    elevator: int | None
    accessibility_required: int | None
    tags: str
    remarks: str
    locations: list[LocationInput]
    created_at: str | None
    updated_at: str | None
    row_version: int
    agency_id: int


class LocationInput(TypedDict):
    location_id: int
    name: NotRequired[str]


class OfferInput(TypedDict, total=False):
    """Payload for creating or updating an offer."""

    id: int
    listing_id: int
    type_id: int | None
    action_id: int | None
    wilaya_id: int | None
    location: str
    beds: int
    surface: float
    budget: int
    furnished: str
    floor: int
    elevator: int
    accessibility_supported: int
    link: str
    latitude: float | None
    longitude: float | None
    remarks: str
    created_at: str | None
    updated_at: str | None
    price_negotiable: int
    price_flex_pct: float
    row_version: int
    status: str
    agency_id: int


class ListingInput(TypedDict, total=False):
    """Payload for creating or updating a listing."""

    id: int
    family_name: str
    phone: str
    remarks: str
    is_vip: int
    status: str
    created_at: str | None
    created_loc: str
    updated_at: str | None
    row_version: int
    agency_id: int
    family_name_enc: str
    family_name_search_src: str | None
    phone_enc: str
    phone_search_src: str | None
    remarks_enc: str


class ContractInput(TypedDict, total=False):
    """Payload for creating or updating a contract."""

    id: int
    client_id: int
    listing_id: int
    contract_type: str
    status: str
    start_date: str | None
    end_date: str | None
    amount: float
    deposit: float
    terms: str
    notes: str
    created_at: str | None
    updated_at: str | None
    row_version: int
    agency_id: int
