"""
Core validation helpers for import operations.
"""

from __future__ import annotations

import re

from core.importer.validation.errors import ImportValidationError
from core.importer.validation.validator_rules import get_dangerous_patterns


def sanitize_string(
    value: str | None,
    field_name: str = "field",
    max_length: int = 500,
    allow_empty: bool = True,
) -> str:
    """Sanitize a string input."""
    if value is None:
        value = ""

    if not isinstance(value, str):
        value = str(value)

    # Strip whitespace
    value = value.strip()

    if not value:
        if not allow_empty:
            raise ImportValidationError(field_name, "Value cannot be empty")
        return ""

    # Check length
    if len(value) > max_length:
        raise ImportValidationError(
            field_name,
            f"Value exceeds maximum length of {max_length}",
            value[:50] + "...",
        )

    # Check for dangerous patterns
    for pattern in get_dangerous_patterns():
        if pattern.search(value):
            raise ImportValidationError(
                field_name,
                "Invalid characters or patterns detected",
                value[:50] + "..." if len(value) > 50 else value,
            )

    # Strip control characters (but keep Arabic, French accents, etc.)
    # Only remove ASCII control chars
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)

    return value


def validate_phone(value: str, field_name: str = "phone") -> str:
    """Validate phone number (after normalization)."""
    if not value:
        return ""

    # Phone should be digits only after normalization
    if not re.match(r"^\d{10}$", value):
        raise ImportValidationError(
            field_name,
            "Phone must be exactly 10 digits",
            value,
        )

    return value


def validate_price(value: float | int | str | None, field_name: str = "price") -> float | None:
    """Validate price value (float/double precision)."""
    if value is None:
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        float_value = float(value)
    else:
        from core.importer.normalizers.price import PriceNormalizer

        raw_text = str(value).strip()
        normalized_result = PriceNormalizer().normalize(raw_text)
        normalized_value = normalized_result.value
        if isinstance(normalized_value, (int, float)):
            float_value = float(normalized_value)
        elif bool(normalized_result.extracted_extras.get("negative_price_detected", False)):
            float_value = -1.0
        else:
            float_value = None

    if float_value is None:
        raise ImportValidationError(
            field_name,
            "Price must be a valid number",
            value,
        )

    value = float(float_value)

    if value < 0:
        raise ImportValidationError(
            field_name,
            "Price cannot be negative",
            value,
        )

    # Reasonable upper bound (100 billion DA)
    if value > 100_000_000_000.0:
        raise ImportValidationError(
            field_name,
            "Price exceeds reasonable maximum",
            value,
        )

    return value


def validate_name(
    value: str,
    field_name: str = "name",
    max_length: int = 100,
) -> str:
    """Validate a name field (person or family name)."""
    # First sanitize
    value = sanitize_string(value, field_name, max_length, allow_empty=True)

    if not value:
        return ""

    # Names can contain letters (any script), spaces, hyphens, apostrophes
    # Allow Arabic, French, Berber names
    # Remove digits and most special characters
    if re.search(r"[\d@#$%^&*()+=\[\]{}|\\<>?/~`]", value):
        raise ImportValidationError(
            field_name,
            "Name contains invalid characters",
            value,
        )

    return value


def validate_email(value: str | None, field_name: str = "email") -> str:
    """Validate email format."""
    if not value:
        return ""

    value = sanitize_string(value, field_name, 254)

    # Basic email pattern
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        raise ImportValidationError(
            field_name,
            "Invalid email format",
            value,
        )

    return value.lower()


def validate_positive_integer(
    value: int | str | None,
    field_name: str,
    max_value: int | None = None,
) -> int | None:
    """Validate a positive integer."""
    if value is None or value == "":
        return None

    from core.importer.type_parser import TypeParser

    try:
        int_value = TypeParser.parse_int(str(value), default=None)
    except Exception:
        int_value = None

    if int_value is None:
        raise ImportValidationError(
            field_name,
            "Must be a valid integer",
            value,
        )

    if int_value < 0:
        raise ImportValidationError(
            field_name,
            "Value cannot be negative",
            int_value,
        )

    if max_value is not None and int_value > max_value:
        raise ImportValidationError(
            field_name,
            f"Value exceeds maximum of {max_value}",
            int_value,
        )

    return int_value


__all__ = [
    "sanitize_string",
    "validate_email",
    "validate_name",
    "validate_phone",
    "validate_positive_integer",
    "validate_price",
]
