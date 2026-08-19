"""
Custom exceptions for import validation.
"""

from __future__ import annotations

from typing import Any


class ImportValidationError(Exception):
    """Raised when import validation fails."""

    def __init__(self, field: str, message: str, value: Any = None) -> None:
        self.field = field
        self.message = message
        self.value = value
        super().__init__(f"{field}: {message}")


__all__ = ["ImportValidationError"]
