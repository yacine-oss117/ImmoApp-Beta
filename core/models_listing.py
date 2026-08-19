from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypedDict, cast

from core.encryption import get_optional_encryption_service
from core.models_cast import as_int, as_str, row_value
from core.utils.common import sanitize_text

logger = logging.getLogger(__name__)


class ListingDict(TypedDict):
    """A dictionary representation of a Listing for database interchange."""

    id: int
    family_name: str
    phone: str
    remarks: str
    is_vip: int | bool
    status: str
    deleted_at: str
    created_at: str
    created_loc: str
    updated_at: str
    row_version: int
    family_name_enc: str
    family_name_search_idx: list[bytes]
    phone_enc: str
    remarks_enc: str
    phone_search_idx: list[bytes]


@dataclass
class Listing:
    """
    A property listing available for sale or rent.

    Required fields:
        id: Auto-generated INTEGER PRIMARY KEY

    Optional fields have sensible defaults.
    """

    id: int = 0
    family_name: str = ""  # Owner/contact name
    phone: str = ""
    remarks: str = ""
    is_vip: bool = False
    status: str = "available"  # available, rented, sold
    deleted_at: str = ""
    created_at: str = ""
    created_loc: str = ""
    updated_at: str = ""
    row_version: int = 1
    family_name_enc: str = ""
    family_name_search_idx: list[bytes] = field(default_factory=list)
    phone_enc: str = ""
    remarks_enc: str = ""
    phone_search_idx: list[bytes] = field(default_factory=list)
    sync_status: str | None = None
    sync_error: str = ""
    is_local_only: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> Listing:
        """Create a Listing from a database row with transparent ALE decryption."""
        # 1. Base values from row
        family_name = as_str(row_value(row, "family_name"))
        phone = as_str(row_value(row, "phone"))

        family_name_enc = as_str(row_value(row, "family_name_enc"))
        phone_enc = as_str(row_value(row, "phone_enc"))
        remarks_enc = as_str(row_value(row, "remarks_enc"))
        enc = (
            get_optional_encryption_service()
            if (family_name_enc or phone_enc or remarks_enc)
            else None
        )

        # 2. Transparent Decryption (Phase B)
        if family_name_enc and enc is not None:
            try:
                family_name = sanitize_text(enc.decrypt(family_name_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt listing family_name_enc; falling back to plaintext",
                    exc_info=True,
                )

        if phone_enc and enc is not None:
            try:
                phone = sanitize_text(enc.decrypt(phone_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt listing phone_enc; falling back to plaintext",
                    exc_info=True,
                )

        remarks = as_str(row_value(row, "remarks"))
        if remarks_enc and enc is not None:
            try:
                remarks = sanitize_text(enc.decrypt(remarks_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt listing remarks_enc; falling back to plaintext",
                    exc_info=True,
                )

        return cls(
            id=as_int(row["id"]),
            family_name=family_name,
            phone=phone,
            remarks=remarks,
            is_vip=bool(row_value(row, "is_vip")),
            status=as_str(row_value(row, "status"), default="available"),
            deleted_at=as_str(row_value(row, "deleted_at")),
            created_at=as_str(row_value(row, "created_at")),
            created_loc=as_str(row_value(row, "created_loc")),
            updated_at=as_str(row_value(row, "updated_at")),
            row_version=as_int(row_value(row, "row_version"), default=1),
            family_name_enc=family_name_enc,
            family_name_search_idx=(
                cast(list[bytes], row_value(row, "family_name_search_idx"))
                if isinstance(row_value(row, "family_name_search_idx"), list)
                else []
            ),
            phone_enc=phone_enc,
            remarks_enc=remarks_enc,
            phone_search_idx=(
                cast(list[bytes], row_value(row, "phone_search_idx"))
                if isinstance(row_value(row, "phone_search_idx"), list)
                else []
            ),
        )

    def to_dict(self) -> ListingDict:
        """Convert to dictionary for database operations."""
        return {
            "id": self.id,
            "family_name": self.family_name,
            "phone": self.phone,
            "remarks": self.remarks,
            "is_vip": 1 if self.is_vip else 0,
            "status": self.status,
            "deleted_at": self.deleted_at,
            "created_at": self.created_at,
            "created_loc": self.created_loc,
            "updated_at": self.updated_at,
            "row_version": self.row_version,
            "family_name_enc": self.family_name_enc,
            "family_name_search_idx": self.family_name_search_idx or [],
            "phone_enc": self.phone_enc,
            "remarks_enc": self.remarks_enc,
            "phone_search_idx": self.phone_search_idx or [],
        }
