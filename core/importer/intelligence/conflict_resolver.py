"""
Duplicate row detector for import data.

Identifies potential duplicate rows based on key fields like phone, name, etc.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DuplicateMatch:
    """Represents a potential duplicate match.

    Attributes:
        row_index: Index of the current row.
        matched_row_index: Index of the matching (earlier) row.
        matched_fields: List of fields that matched.
        confidence: How confident we are this is a duplicate (0.0-1.0).
    """

    row_index: int
    matched_row_index: int
    matched_fields: list[str]
    confidence: float

    @property
    def is_exact_match(self) -> bool:
        """True if this is an exact duplicate (confidence = 1.0)."""
        return self.confidence >= 1.0


@dataclass
class DuplicateDetectionResult:
    """Result of duplicate detection on a batch of rows.

    Attributes:
        duplicates: List of potential duplicate matches.
        unique_count: Number of unique rows.
        duplicate_count: Number of duplicate rows.
    """

    duplicates: list[DuplicateMatch] = field(default_factory=list)
    unique_count: int = 0
    duplicate_count: int = 0

    @property
    def has_duplicates(self) -> bool:
        """True if any duplicates were found."""
        return len(self.duplicates) > 0


class DuplicateDetector:
    """Detects potential duplicate rows in import data.

    Uses configurable key fields to identify duplicates.
    Phone numbers and emails are primary identifiers.

    Example:
        detector = DuplicateDetector(key_fields=["phone", "email"])
        result = detector.detect(rows)
        for dup in result.duplicates:
            print(f"Row {dup.row_index} duplicates row {dup.matched_row_index}")
    """

    # Default fields to check for duplicates
    DEFAULT_KEY_FIELDS = ["phone", "tel", "telephone", "email", "nom", "name"]

    def __init__(
        self,
        key_fields: list[str] | None = None,
        normalizers: dict[str, Callable[[str], str]] | None = None,
        min_confidence: float = 0.8,
    ) -> None:
        """Initialize duplicate detector.

        Args:
            key_fields: Fields to use for duplicate detection. Case-insensitive.
            normalizers: Optional normalizer functions per field type.
            min_confidence: Minimum confidence to report as duplicate.
        """
        self.key_fields = [f.lower() for f in (key_fields or self.DEFAULT_KEY_FIELDS)]
        self.normalizers = normalizers or {}
        self.min_confidence = min_confidence

    def detect(self, rows: list[dict[str, str]]) -> DuplicateDetectionResult:
        """Detect duplicates in a list of rows.

        Args:
            rows: List of row dictionaries from parser.

        Returns:
            DuplicateDetectionResult with duplicate information.
        """
        if not rows:
            return DuplicateDetectionResult(unique_count=0, duplicate_count=0)

        duplicates: list[DuplicateMatch] = []
        seen_values: dict[str, list[tuple[int, str]]] = {}  # value -> [(row_idx, field)]

        for row_idx, row in enumerate(rows):
            row_duplicates: list[tuple[int, str, float]] = []  # (matched_idx, field, conf)

            # Check each key field
            for col_name, value in row.items():
                col_lower = col_name.lower()

                # Find matching key field
                matching_key = self._find_matching_key(col_lower)
                if not matching_key:
                    continue

                # Normalize value
                normalized = self._normalize_value(value, matching_key)
                if not normalized:
                    continue

                # Check if we've seen this value before
                if normalized in seen_values:
                    for prev_idx, _prev_field in seen_values[normalized]:
                        confidence = self._calculate_confidence(matching_key, normalized)
                        row_duplicates.append((prev_idx, matching_key, confidence))

                # Remember this value
                if normalized not in seen_values:
                    seen_values[normalized] = []
                seen_values[normalized].append((row_idx, matching_key))

            # If this row has duplicates, create a match record
            if row_duplicates:
                # Group by matched row index
                by_matched_row: dict[int, list[tuple[str, float]]] = {}
                for matched_idx, fld, conf in row_duplicates:
                    if matched_idx not in by_matched_row:
                        by_matched_row[matched_idx] = []
                    by_matched_row[matched_idx].append((fld, conf))

                # Create duplicate match for each matched row
                for matched_idx, fields_confs in by_matched_row.items():
                    fields = [f for f, _ in fields_confs]
                    max_conf = max(c for _, c in fields_confs)

                    if max_conf >= self.min_confidence:
                        duplicates.append(
                            DuplicateMatch(
                                row_index=row_idx,
                                matched_row_index=matched_idx,
                                matched_fields=fields,
                                confidence=max_conf,
                            )
                        )

        # Count unique vs duplicate rows
        duplicate_row_indices = {d.row_index for d in duplicates}
        unique_count = len(rows) - len(duplicate_row_indices)

        return DuplicateDetectionResult(
            duplicates=duplicates,
            unique_count=unique_count,
            duplicate_count=len(duplicate_row_indices),
        )

    def _find_matching_key(self, col_name: str) -> str | None:
        """Find which key field matches this column name."""
        for key in self.key_fields:
            if key in col_name or col_name in key:
                return key
        return None

    def _normalize_value(self, value: str, field_type: str) -> str:
        """Normalize a value for comparison."""
        if not value:
            return ""

        # Apply custom normalizer if available
        if field_type in self.normalizers:
            return self.normalizers[field_type](value)

        # Default normalization
        normalized = value.strip().lower()

        # Special handling for phone numbers
        if field_type in ("phone", "tel", "telephone"):
            # Remove all non-digits
            normalized = "".join(c for c in normalized if c.isdigit())
            # Remove leading country code
            if normalized.startswith("213"):
                normalized = "0" + normalized[3:]
            elif normalized.startswith("00213"):
                normalized = "0" + normalized[5:]
            # Ensure 10 digits for Algerian numbers
            if len(normalized) == 9 and normalized[0] in "567":
                normalized = "0" + normalized

        # Special handling for email
        elif field_type == "email":
            normalized = normalized.replace(" ", "")

        return normalized

    def _calculate_confidence(self, field_type: str, value: str) -> float:
        """Calculate confidence score for a match.

        Phone and email matches are high confidence.
        Name matches are lower confidence.
        """
        if field_type in ("phone", "tel", "telephone"):
            # Phone match = very high confidence
            if len(value) >= 9:
                return 1.0
            return 0.9

        elif field_type == "email":
            # Email match = very high confidence
            return 1.0

        elif field_type in ("nom", "name"):
            # Name match = medium confidence (names can repeat)
            return 0.6

        return 0.5
