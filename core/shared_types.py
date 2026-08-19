"""
Shared TypedDict definitions for app-level payloads.
"""

from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired


class VisitData(TypedDict):
    """Payload for creating or updating a property visit."""

    client_id: int
    listing_id: int
    scheduled_date: str
    scheduled_time: NotRequired[str]
    status: NotRequired[str]
    notes: NotRequired[str]
    row_version: NotRequired[int]
    agency_id: NotRequired[int]


class ContractData(TypedDict):
    """Payload for creating or updating a contract."""

    client_id: int
    listing_id: int
    contract_type: str
    amount: float
    deposit: NotRequired[float]
    terms: NotRequired[str]
    notes: NotRequired[str]
    status: NotRequired[str]
    start_date: NotRequired[str | None]
    end_date: NotRequired[str | None]
    row_version: NotRequired[int]
    agency_id: NotRequired[int]


class ContractUpdateData(TypedDict, total=False):
    """Payload for updating a contract."""

    contract_type: str
    amount: float
    deposit: float
    terms: str
    notes: str
    status: str
    start_date: str | None
    end_date: str | None
    row_version: int


class TemplateContext(TypedDict):
    """Context data for rendering WhatsApp templates."""

    client_name: str
    agency_name: str
    date: str
    time: str
    location: str
    price: str
    type: str
