"""
CRM domain models (Contracts and Visits).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict

from core.encryption import get_optional_encryption_service
from core.models_cast import as_int, as_optional_float, as_str, row_value
from core.utils.common import sanitize_text

logger = logging.getLogger(__name__)


class VisitDict(TypedDict):
    id: int
    client_id: int
    listing_id: int
    scheduled_date: str
    scheduled_time: str
    status: str
    notes: str
    notes_enc: str
    deleted_at: str
    created_at: str
    updated_at: str
    row_version: int


class ContractDict(TypedDict):
    id: int
    client_id: int
    listing_id: int
    contract_type: str
    status: str
    start_date: str
    end_date: str
    amount: float | None
    deposit: float | None
    terms: str
    notes: str
    amount_enc: str
    deposit_enc: str
    terms_enc: str
    notes_enc: str
    deleted_at: str
    created_at: str
    updated_at: str
    row_version: int


@dataclass
class Visit:
    """
    A scheduled property visit/viewing.
    """

    id: int = 0
    client_id: int = 0
    listing_id: int = 0
    scheduled_date: str = ""
    scheduled_time: str = ""
    status: str = "scheduled"
    notes: str = ""
    deleted_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    row_version: int = 1

    notes_enc: str = ""

    # Joined data
    client_name: str = ""
    listing_location: str = ""
    sync_status: str | None = None
    sync_error: str = ""
    is_local_only: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> Visit:
        """Create a Visit from a database row with ALE support."""
        keys = row.keys()
        notes = as_str(row_value(row, "notes"))
        notes_enc = as_str(row_value(row, "notes_enc")) if "notes_enc" in keys else ""
        enc = get_optional_encryption_service() if notes_enc else None

        if notes_enc and enc is not None:
            try:
                notes = sanitize_text(enc.decrypt(notes_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt visit notes_enc; falling back to plaintext",
                    exc_info=True,
                )

        return cls(
            id=as_int(row["id"]),
            client_id=as_int(row["client_id"]),
            listing_id=as_int(row["listing_id"]),
            scheduled_date=as_str(row_value(row, "scheduled_date")),
            scheduled_time=as_str(row_value(row, "scheduled_time")),
            status=as_str(row_value(row, "status"), default="scheduled"),
            notes=notes,
            notes_enc=notes_enc,
            deleted_at=as_str(row_value(row, "deleted_at")) if "deleted_at" in keys else "",
            created_at=as_str(row_value(row, "created_at")),
            updated_at=as_str(row_value(row, "updated_at")),
            row_version=as_int(row_value(row, "row_version"), default=1),
            client_name=as_str(row_value(row, "client_name")) if "client_name" in keys else "",
            listing_location=(
                as_str(row_value(row, "listing_location")) if "listing_location" in keys else ""
            ),
        )

    def to_dict(self) -> VisitDict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "listing_id": self.listing_id,
            "scheduled_date": self.scheduled_date,
            "scheduled_time": self.scheduled_time,
            "status": self.status,
            "notes": self.notes,
            "notes_enc": self.notes_enc,
            "deleted_at": self.deleted_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "row_version": self.row_version,
        }


@dataclass
class Contract:
    """
    A rental or purchase contract between client and property.
    """

    id: int = 0
    client_id: int = 0
    listing_id: int = 0
    contract_type: str = ""
    status: str = "draft"
    start_date: str = ""
    end_date: str = ""
    amount: float | None = None
    deposit: float | None = None
    terms: str = ""
    notes: str = ""
    deleted_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    row_version: int = 1

    amount_enc: str = ""
    deposit_enc: str = ""
    terms_enc: str = ""
    notes_enc: str = ""

    # Joined data
    client_name: str = ""
    listing_location: str = ""
    sync_status: str | None = None
    sync_error: str = ""
    is_local_only: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> Contract:
        """Create a Contract from a database row with ALE support."""
        keys = row.keys()
        amount = as_optional_float(row_value(row, "amount"))
        deposit = as_optional_float(row_value(row, "deposit"))
        terms = as_str(row_value(row, "terms"))
        notes = as_str(row_value(row, "notes"))

        amount_enc = as_str(row_value(row, "amount_enc")) if "amount_enc" in keys else ""
        deposit_enc = as_str(row_value(row, "deposit_enc")) if "deposit_enc" in keys else ""
        terms_enc = as_str(row_value(row, "terms_enc")) if "terms_enc" in keys else ""
        notes_enc = as_str(row_value(row, "notes_enc")) if "notes_enc" in keys else ""
        enc = (
            get_optional_encryption_service()
            if (amount_enc or deposit_enc or terms_enc or notes_enc)
            else None
        )

        if amount_enc and enc is not None:
            try:
                amount = float(enc.decrypt(amount_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt contract amount_enc; falling back to plaintext",
                    exc_info=True,
                )
        if deposit_enc and enc is not None:
            try:
                deposit = float(enc.decrypt(deposit_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt contract deposit_enc; falling back to plaintext",
                    exc_info=True,
                )
        if terms_enc and enc is not None:
            try:
                terms = sanitize_text(enc.decrypt(terms_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt contract terms_enc; falling back to plaintext",
                    exc_info=True,
                )
        if notes_enc and enc is not None:
            try:
                notes = sanitize_text(enc.decrypt(notes_enc))
            except Exception:
                logger.debug(
                    "Failed to decrypt contract notes_enc; falling back to plaintext",
                    exc_info=True,
                )

        return cls(
            id=as_int(row["id"]),
            client_id=as_int(row["client_id"]),
            listing_id=as_int(row["listing_id"]),
            contract_type=as_str(row_value(row, "contract_type")),
            status=as_str(row_value(row, "status"), default="draft"),
            start_date=as_str(row_value(row, "start_date")),
            end_date=as_str(row_value(row, "end_date")),
            amount=amount,
            deposit=deposit,
            terms=terms,
            notes=notes,
            deleted_at=as_str(row_value(row, "deleted_at")) if "deleted_at" in keys else "",
            created_at=as_str(row_value(row, "created_at")),
            updated_at=as_str(row_value(row, "updated_at")),
            row_version=as_int(row_value(row, "row_version"), default=1),
            amount_enc=amount_enc,
            deposit_enc=deposit_enc,
            terms_enc=terms_enc,
            notes_enc=notes_enc,
            client_name=as_str(row_value(row, "client_name")) if "client_name" in keys else "",
            listing_location=(
                as_str(row_value(row, "listing_location")) if "listing_location" in keys else ""
            ),
        )

    def to_dict(self) -> ContractDict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "listing_id": self.listing_id,
            "contract_type": self.contract_type,
            "status": self.status,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "amount": self.amount,
            "deposit": self.deposit,
            "terms": self.terms,
            "notes": self.notes,
            "amount_enc": self.amount_enc,
            "deposit_enc": self.deposit_enc,
            "terms_enc": self.terms_enc,
            "notes_enc": self.notes_enc,
            "deleted_at": self.deleted_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "row_version": self.row_version,
        }
