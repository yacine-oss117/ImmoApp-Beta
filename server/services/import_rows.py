"""
Row normalization and validation helpers for import operations.
"""

from __future__ import annotations

from typing import Any, cast

from core.data.types import ClientInput, DemandeInput, ListingInput, OfferInput
from core.importer.type_parser import TypeParser
from core.importer.validation import ImportValidationError, ImportValidator
from server.services.clients import normalize_client_data
from server.services.listings import normalize_listing_data


def normalize_client_batch(rows: list[dict[str, Any]]) -> list[ClientInput]:
    return [cast(ClientInput, normalize_client_data(r)) for r in rows]


def normalize_listing_batch(rows: list[dict[str, Any]]) -> list[ListingInput]:
    return [cast(ListingInput, normalize_listing_data(r)) for r in rows]


def normalize_demande_batch(rows: list[dict[str, Any]]) -> list[DemandeInput]:
    return [cast(DemandeInput, dict(r)) for r in rows]


def normalize_offer_batch(rows: list[dict[str, Any]]) -> list[OfferInput]:
    return [cast(OfferInput, dict(r)) for r in rows]


def _parse_boolish(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    parsed = TypeParser.parse_bool(str(value), default=None)
    if parsed is None:
        return None
    return 1 if parsed else 0


def validate_row(row: dict[str, Any], entity_type: str) -> tuple[dict[str, Any], list[str]]:
    """Validate a single row using ImportValidator."""
    errors: list[str] = []
    validated: dict[str, Any] = {}

    for name_field in ["name", "family_name", "first_name"]:
        if name_field in row:
            try:
                validated[name_field] = ImportValidator.validate_name(row[name_field], name_field)
            except ImportValidationError as e:
                errors.append(str(e))

    if "phone" in row:
        try:
            validated["phone"] = ImportValidator.validate_phone(row["phone"], "phone")
        except ImportValidationError as e:
            errors.append(str(e))

    for price_field in [
        "price",
        "budget",
        "budget_min",
        "budget_max",
        "surface",
        "surface_min",
        "surface_max",
        "latitude",
        "longitude",
        "price_flex_pct",
    ]:
        if price_field in row:
            try:
                validated[price_field] = ImportValidator.validate_price(
                    row[price_field], price_field
                )
            except ImportValidationError as e:
                errors.append(str(e))

    for int_field in [
        "client_id",
        "listing_id",
        "type_id",
        "action_id",
        "wilaya_id",
        "beds",
        "beds_min",
        "floor",
        "floor_min",
        "floor_max",
    ]:
        if int_field in row:
            try:
                validated[int_field] = ImportValidator.validate_positive_integer(
                    row[int_field], int_field
                )
            except ImportValidationError as e:
                errors.append(str(e))

    if "email" in row:
        try:
            validated["email"] = ImportValidator.validate_email(row["email"], "email")
        except ImportValidationError as e:
            errors.append(str(e))

    for bool_field in [
        "elevator",
        "parking",
        "accessibility_required",
        "accessibility_supported",
        "price_negotiable",
    ]:
        if bool_field in row:
            parsed_bool = _parse_boolish(row[bool_field])
            if parsed_bool is None and row[bool_field] not in (None, ""):
                errors.append(f"{bool_field}: invalid boolean value")
            validated[bool_field] = parsed_bool

    for key, value in row.items():
        if key not in validated:
            if isinstance(value, str):
                try:
                    validated[key] = ImportValidator.sanitize_string(value, key)
                except ImportValidationError as e:
                    errors.append(str(e))
            else:
                validated[key] = value

    # Entity-specific strict guardrails (asymmetric model).
    if entity_type == "demande":
        for required_field in ["action", "type", "wilaya"]:
            if not validated.get(required_field):
                errors.append(f"{required_field} is required for demandes")
        budget_min = validated.get("budget_min")
        budget_max = validated.get("budget_max")
        surface_min = validated.get("surface_min")
        surface_max = validated.get("surface_max")
        if isinstance(budget_min, (int, float)) and isinstance(budget_max, (int, float)):
            if budget_min > budget_max:
                errors.append("budget_min cannot be greater than budget_max")
        if isinstance(surface_min, (int, float)) and isinstance(surface_max, (int, float)):
            if surface_min > surface_max:
                errors.append("surface_min cannot be greater than surface_max")
        if validated.get("floor_min") is None:
            validated["floor_min"] = 0
        if validated.get("floor_max") is None:
            validated["floor_max"] = 100
    elif entity_type == "offer":
        for required_field in [
            "action",
            "type",
            "wilaya",
            "location",
            "budget",
            "surface",
            "beds",
            "floor",
        ]:
            val = validated.get(required_field)
            if val is None or val == "":
                errors.append(f"{required_field} is required for offers")

    return validated, errors


__all__ = [
    "normalize_client_batch",
    "normalize_listing_batch",
    "normalize_demande_batch",
    "normalize_offer_batch",
    "validate_row",
]
