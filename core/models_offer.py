"""
Offer domain model and typed dict.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict

from core.encryption import get_optional_encryption_service
from core.models_cast import as_int, as_optional_float, as_optional_int, as_str, row_value
from core.utils.common import sanitize_text

logger = logging.getLogger(__name__)


class OfferDict(TypedDict):
    """A dictionary representation of an Offer for database interchange."""

    id: int
    listing_id: int
    type: str
    type_id: int | None
    action: str
    action_id: int | None
    wilaya: str
    wilaya_id: int | None
    location: str
    beds: int | None
    surface: float | None
    budget: float | None
    furnished: str
    floor: int
    elevator: int
    accessibility_supported: int
    price_negotiable: int
    price_flex_pct: float
    link: str

    latitude: float | None
    longitude: float | None
    remarks: str
    status: str
    deleted_at: str
    created_at: str
    updated_at: str
    row_version: int
    remarks_enc: str
    location_enc: str


@dataclass
class Offer:
    """
    A property offer from a listing owner.

    One listing owner can have multiple offers (properties in different locations).
    """

    id: int = 0
    listing_id: int = 0
    type: str = ""  # apartment, house, business, land
    type_id: int | None = None
    action: str = ""  # sell, rent
    action_id: int | None = None
    wilaya: str = ""  # For analytics/contracts
    wilaya_id: int | None = None
    location: str = ""  # Specific location
    beds: int | None = None
    surface: float | None = None
    budget: float | None = None  # Price
    furnished: str = ""
    floor: int = 0
    elevator: bool = False
    accessibility_supported: bool = False
    price_negotiable: bool = False
    price_flex_pct: float = 0.0
    link: str = ""  # URL/position

    latitude: float | None = None
    longitude: float | None = None
    remarks: str = ""
    status: str = "available"
    deleted_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    row_version: int = 1
    remarks_enc: str = ""
    location_enc: str = ""
    sync_status: str | None = None
    sync_error: str = ""
    is_local_only: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> Offer:
        """Create an Offer from a database row with ALE support."""
        keys = row.keys()
        remarks = as_str(row_value(row, "remarks"))
        remarks_enc = as_str(row_value(row, "remarks_enc")) if "remarks_enc" in keys else ""

        location = as_str(row_value(row, "location"))
        location_enc = as_str(row_value(row, "location_enc")) if "location_enc" in keys else ""
        enc = get_optional_encryption_service() if (remarks_enc or location_enc) else None

        if remarks_enc and enc is not None:
            try:
                remarks = sanitize_text(enc.decrypt(remarks_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt offer remarks_enc; falling back to plaintext",
                    exc_info=True,
                )

        if location_enc and enc is not None:
            try:
                location = sanitize_text(enc.decrypt(location_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt offer location_enc; falling back to plaintext",
                    exc_info=True,
                )

        return cls(
            id=as_int(row["id"]),
            listing_id=as_int(row["listing_id"]),
            type=as_str(row_value(row, "type")),
            type_id=(as_optional_int(row_value(row, "type_id")) if "type_id" in keys else None),
            action=as_str(row_value(row, "action")),
            action_id=(
                as_optional_int(row_value(row, "action_id")) if "action_id" in keys else None
            ),
            wilaya=as_str(row_value(row, "wilaya")) if "wilaya" in keys else "",
            wilaya_id=(
                as_optional_int(row_value(row, "wilaya_id")) if "wilaya_id" in keys else None
            ),
            location=location,
            beds=as_optional_int(row_value(row, "beds")),
            surface=as_optional_float(row_value(row, "surface")),
            budget=as_optional_float(row_value(row, "budget")),
            furnished=as_str(row_value(row, "furnished")),
            floor=as_int(row_value(row, "floor"), default=0),
            elevator=bool(row_value(row, "elevator")),
            accessibility_supported=bool(row_value(row, "accessibility_supported")),
            price_negotiable=bool(row_value(row, "price_negotiable")),
            price_flex_pct=as_optional_float(row_value(row, "price_flex_pct")) or 0.0,
            link=as_str(row_value(row, "link")),
            latitude=as_optional_float(row_value(row, "latitude")),
            longitude=as_optional_float(row_value(row, "longitude")),
            remarks=remarks,
            status=as_str(row_value(row, "status")) if "status" in keys else "available",
            deleted_at=as_str(row_value(row, "deleted_at")) if "deleted_at" in keys else "",
            created_at=as_str(row_value(row, "created_at")),
            updated_at=as_str(row_value(row, "updated_at")),
            row_version=as_int(row_value(row, "row_version"), default=1),
            remarks_enc=remarks_enc,
            location_enc=location_enc,
        )

    def to_dict(self) -> OfferDict:
        """Convert to dictionary for database operations."""
        return {
            "id": self.id,
            "listing_id": self.listing_id,
            "type": self.type,
            "type_id": self.type_id,
            "action": self.action,
            "action_id": self.action_id,
            "wilaya": self.wilaya,
            "wilaya_id": self.wilaya_id,
            "location": self.location,
            "beds": self.beds,
            "surface": self.surface,
            "budget": self.budget,
            "furnished": self.furnished,
            "floor": self.floor,
            "elevator": 1 if self.elevator else 0,
            "accessibility_supported": 1 if self.accessibility_supported else 0,
            "price_negotiable": 1 if self.price_negotiable else 0,
            "price_flex_pct": self.price_flex_pct,
            "link": self.link,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "remarks": self.remarks,
            "status": self.status,
            "deleted_at": self.deleted_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "row_version": self.row_version,
            "remarks_enc": self.remarks_enc,
            "location_enc": self.location_enc,
        }
