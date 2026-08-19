"""
Input validation and sanitization for import operations.

Provides SQL injection protection and field-specific validation.
"""

from __future__ import annotations

from core.importer.validation.validator_core import (
    sanitize_string,
    validate_email,
    validate_name,
    validate_phone,
    validate_positive_integer,
    validate_price,
)


class ImportValidator:
    """Validate and sanitize all imported data.

    Provides protection against:
    - SQL injection attempts
    - Control characters
    - Oversized inputs
    - Invalid field formats
    """

    @staticmethod
    def sanitize_string(
        value: str | None,
        field_name: str = "field",
        max_length: int = 500,
        allow_empty: bool = True,
    ) -> str:
        """Sanitize a string input.

        Args:
            value: The input value to sanitize.
            field_name: Name of field for error messages.
            max_length: Maximum allowed length.
            allow_empty: Whether empty values are allowed.

        Returns:
            Sanitized string.

        Raises:
            ImportValidationError: If validation fails.
        """
        return sanitize_string(value, field_name, max_length, allow_empty)

    @staticmethod
    def validate_phone(value: str, field_name: str = "phone") -> str:
        """Validate phone number (after normalization).

        Args:
            value: Normalized phone number.
            field_name: Name of field for error messages.

        Returns:
            Validated phone number.

        Raises:
            ImportValidationError: If validation fails.
        """
        return validate_phone(value, field_name)

    @staticmethod
    def validate_price(value: float | int | str | None, field_name: str = "price") -> float | None:
        """Validate price value (float/double precision).

        Args:
            value: Price value.
            field_name: Name of field for error messages.

        Returns:
            Validated price as float.

        Raises:
            ImportValidationError: If validation fails.
        """
        return validate_price(value, field_name)

    @staticmethod
    def validate_name(
        value: str,
        field_name: str = "name",
        max_length: int = 100,
    ) -> str:
        """Validate a name field (person or family name).

        Args:
            value: Name value.
            field_name: Name of field for error messages.
            max_length: Maximum allowed length.

        Returns:
            Validated name.

        Raises:
            ImportValidationError: If validation fails.
        """
        return validate_name(value, field_name, max_length)

    @staticmethod
    def validate_email(value: str | None, field_name: str = "email") -> str:
        """Validate email format.

        Args:
            value: Email value.
            field_name: Name of field for error messages.

        Returns:
            Validated email.

        Raises:
            ImportValidationError: If validation fails.
        """
        return validate_email(value, field_name)

    @staticmethod
    def validate_positive_integer(
        value: int | str | None,
        field_name: str,
        max_value: int | None = None,
    ) -> int | None:
        """Validate a positive integer.

        Args:
            value: Integer value.
            field_name: Name of field for error messages.
            max_value: Optional maximum value.

        Returns:
            Validated integer.

        Raises:
            ImportValidationError: If validation fails.
        """
        return validate_positive_integer(value, field_name, max_value)
