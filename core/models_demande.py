"""
Demande domain model and typed dict.
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


class DemandeDict(TypedDict):
    """A dictionary representation of a Demande for database interchange."""

    id: int
    client_id: int
    type: str
    type_id: int | None
    action: str
    action_id: int | None
    wilaya: str
    wilaya_id: int | None
    locations: str
    beds_min: int | None
    surface_min: float | None
    surface_max: float | None
    budget_min: float | None
    budget_max: float | None
    furnished: str
    floor_min: int
    floor_max: int
    elevator: int | None
    accessibility_required: int | None
    tags: str
    remarks: str
    deleted_at: str
    created_at: str
    updated_at: str
    row_version: int
    remarks_enc: str
    locations_enc: str


@dataclass
class Demande:
    """
    A property search request from a client.
    """

    id: int = 0
    client_id: int = 0
    type: str = ""
    type_id: int | None = None
    action: str = ""
    action_id: int | None = None
    wilaya: str = ""
    wilaya_id: int | None = None
    locations: str = ""
    beds_min: int | None = None
    surface_min: float | None = None
    surface_max: float | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    furnished: str = ""
    floor_min: int = 0
    floor_max: int = 100
    elevator: bool | None = None
    accessibility_required: bool | None = None
    tags: str = ""
    remarks: str = ""
    deleted_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    row_version: int = 1
    remarks_enc: str = ""
    locations_enc: str = ""
    sync_status: str | None = None
    sync_error: str = ""
    is_local_only: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> Demande:
        """Create a Demande from a database row with ALE support."""
        keys = row.keys()
        remarks = as_str(row_value(row, "remarks"))
        remarks_enc = as_str(row_value(row, "remarks_enc")) if "remarks_enc" in keys else ""

        locations = as_str(row_value(row, "locations"))
        locations_enc = as_str(row_value(row, "locations_enc")) if "locations_enc" in keys else ""
        enc = get_optional_encryption_service() if (remarks_enc or locations_enc) else None

        if remarks_enc and enc is not None:
            try:
                remarks = sanitize_text(enc.decrypt(remarks_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt demande remarks_enc; falling back to plaintext",
                    exc_info=True,
                )

        if locations_enc and enc is not None:
            try:
                locations = sanitize_text(enc.decrypt(locations_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt demande locations_enc; falling back to plaintext",
                    exc_info=True,
                )

        return cls(
            id=as_int(row["id"]),
            client_id=as_int(row["client_id"]),
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
            locations=locations,
            beds_min=as_optional_int(row_value(row, "beds_min")),
            surface_min=as_optional_float(row_value(row, "surface_min")),
            surface_max=(
                as_optional_float(row_value(row, "surface_max")) if "surface_max" in keys else None
            ),
            budget_min=(
                as_optional_float(row_value(row, "budget_min")) if "budget_min" in keys else None
            ),
            budget_max=as_optional_float(row_value(row, "budget_max")),
            furnished=as_str(row_value(row, "furnished")),
            floor_min=as_int(row_value(row, "floor_min"), default=0),
            floor_max=as_int(row_value(row, "floor_max"), default=100),
            elevator=(
                bool(row_value(row, "elevator")) if row_value(row, "elevator") is not None else None
            ),
            accessibility_required=(
                bool(row_value(row, "accessibility_required"))
                if row_value(row, "accessibility_required") is not None
                else None
            ),
            tags=as_str(row_value(row, "tags")),
            remarks=remarks,
            deleted_at=as_str(row_value(row, "deleted_at")) if "deleted_at" in keys else "",
            created_at=as_str(row_value(row, "created_at")),
            updated_at=as_str(row_value(row, "updated_at")),
            row_version=as_int(row_value(row, "row_version"), default=1),
            remarks_enc=remarks_enc,
            locations_enc=locations_enc,
        )

    def to_dict(self) -> DemandeDict:
        """Convert to dictionary for database operations."""
        return {
            "id": self.id,
            "client_id": self.client_id,
            "type": self.type,
            "type_id": self.type_id,
            "action": self.action,
            "action_id": self.action_id,
            "wilaya": self.wilaya,
            "wilaya_id": self.wilaya_id,
            "locations": self.locations,
            "beds_min": self.beds_min,
            "surface_min": self.surface_min,
            "surface_max": self.surface_max,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "furnished": self.furnished,
            "floor_min": self.floor_min,
            "floor_max": self.floor_max,
            "elevator": 1 if self.elevator else None,
            "accessibility_required": 1 if self.accessibility_required else None,
            "tags": self.tags,
            "remarks": self.remarks,
            "deleted_at": self.deleted_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "row_version": self.row_version,
            "remarks_enc": self.remarks_enc,
            "locations_enc": self.locations_enc,
        }
