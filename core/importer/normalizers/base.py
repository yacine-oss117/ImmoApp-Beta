"""
Base normalizer protocol and shared data structures.

All normalizers return a NormalizeResult with value and confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class NormalizeResult:
    """Result of normalizing a value.

    Attributes:
        value: The normalized value (can be any type).
        confidence: Confidence score from 0.0 to 1.0.
        original: The original input string.
        needs_review: Flag for manual review if confidence is low.
        extracted_extras: Additional fields extracted (for multi-value).
        to_remarks: Text to append to remarks field.
    """

    value: object
    confidence: float
    original: str
    needs_review: bool = False
    extracted_extras: dict[str, object] = field(default_factory=dict)
    to_remarks: str | None = None

    def is_high_confidence(self, threshold: float = 0.85) -> bool:
        """Check if result has high confidence.

        Args:
            threshold: Confidence threshold (default 0.85).

        Returns:
            True if confidence >= threshold.
        """
        return self.confidence >= threshold

    def is_empty(self) -> bool:
        """Check if the normalized value is empty/None.

        Returns:
            True if value is None or empty string.
        """
        return self.value is None or self.value == ""


@dataclass
class RowContext:
    """Context for normalizing a value within a row.

    Provides hints from other columns to improve normalization.

    Attributes:
        wilaya_hint: Wilaya code if known from another column.
        action_hint: Action type (buy/rent) if known.
        type_hint: Property type if known.
        row_data: Full row data for cross-column inference.
    """

    wilaya_hint: str | None = None
    action_hint: str | None = None
    type_hint: str | None = None
    row_data: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


class Normalizer(Protocol):
    """Protocol for field normalizers.

    All normalizers must implement the normalize method.
    """

    def normalize(self, value: str, context: RowContext | None = None) -> NormalizeResult:
        """Normalize a value.

        Args:
            value: The raw value to normalize.
            context: Optional context from other columns.

        Returns:
            NormalizeResult with normalized value and metadata.
        """
        ...
