"""
Column type detector.

Analyzes column headers and values to infer field types.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.importer.detection.column_detector_rules import (
    FIELD_MAPPINGS,
    HEADER_PATTERNS,
    VALUE_PATTERNS,
    normalize_header_phrase,
    tokenize_header,
)


@dataclass
class ColumnTypeResult:
    """Result of column type detection.

    Attributes:
        column_name: Original column name.
        detected_type: Inferred type (phone, price, location, etc.).
        confidence: Confidence score 0.0-1.0.
        suggested_mapping: Suggested database field name.
    """

    column_name: str
    detected_type: str
    confidence: float
    suggested_mapping: str | None = None
    reasons: list[str] = field(default_factory=list)


class ColumnDetector:
    """Detects column types from headers and sample values.

    Uses a combination of header name matching and value pattern
    analysis to infer the most likely field type.
    """

    def detect_column_type(
        self,
        column_name: str,
        sample_values: list[str] | None = None,
    ) -> ColumnTypeResult:
        """Detect the type of a column.

        Args:
            column_name: Column header name.
            sample_values: Optional sample values from the column.

        Returns:
            ColumnTypeResult with detected type and confidence.
        """
        # 1. Try header-based detection
        header_type, header_conf = self._detect_from_header(column_name)

        # 2. Try value-based detection if samples provided
        value_type = None
        value_conf = 0.0
        if sample_values:
            value_type, value_conf = self._detect_from_values(sample_values)

        # 3. Combine results
        if header_conf >= 0.8:
            # High confidence from header
            return ColumnTypeResult(
                column_name=column_name,
                detected_type=header_type,
                confidence=header_conf,
                suggested_mapping=self._get_mapping(header_type),
            )
        elif value_conf >= 0.7 and value_type:
            # Good confidence from values
            return ColumnTypeResult(
                column_name=column_name,
                detected_type=value_type,
                confidence=value_conf,
                suggested_mapping=self._get_mapping(value_type),
            )
        elif header_conf > 0:
            # Lower confidence from header
            return ColumnTypeResult(
                column_name=column_name,
                detected_type=header_type,
                confidence=header_conf,
                suggested_mapping=self._get_mapping(header_type),
            )
        else:
            # Unknown
            return ColumnTypeResult(
                column_name=column_name,
                detected_type="unknown",
                confidence=0.0,
                suggested_mapping=None,
            )

    def detect_all_columns(
        self,
        headers: list[str],
        rows: list[dict[str, str]] | None = None,
    ) -> list[ColumnTypeResult]:
        """Detect types for all columns.

        Args:
            headers: List of column headers.
            rows: Optional rows for value-based detection.

        Returns:
            List of ColumnTypeResult for each column.
        """
        results = []

        for header in headers:
            # Get sample values for this column
            samples = None
            if rows:
                samples = [
                    row.get(header, "") for row in rows[:10] if row.get(header)  # First 10 rows
                ]

            result = self.detect_column_type(header, samples)
            results.append(result)

        return results

    def _detect_from_header(self, column_name: str) -> tuple[str, float]:
        """Detect type from column header name.

        Args:
            column_name: Column header.

        Returns:
            Tuple of (type, confidence).
        """
        header_phrase = normalize_header_phrase(column_name)
        header_tokens = set(tokenize_header(column_name))
        if not header_phrase:
            return ("unknown", 0.0)

        best_by_field: dict[str, float] = {}
        for field_type, patterns in HEADER_PATTERNS.items():
            for pattern in patterns:
                pattern_phrase = normalize_header_phrase(pattern)
                pattern_tokens = set(tokenize_header(pattern))
                score = 0.0
                if header_phrase == pattern_phrase:
                    score = 1.0
                elif pattern_tokens and pattern_tokens.issubset(header_tokens):
                    score = 0.93 if len(pattern_tokens) > 1 else 0.88
                elif (
                    header_tokens
                    and header_tokens.issubset(pattern_tokens)
                    and len(header_tokens) > 1
                ):
                    score = 0.9
                elif pattern_phrase and pattern_phrase.replace(" ", "") == header_phrase.replace(
                    " ", ""
                ):
                    score = 0.97
                if score > 0.0:
                    best_by_field[field_type] = max(best_by_field.get(field_type, 0.0), score)

        if not best_by_field:
            return ("unknown", 0.0)
        candidates = sorted(best_by_field.items(), key=lambda item: item[1], reverse=True)
        best_type, best_score = candidates[0]
        second_score = candidates[1][1] if len(candidates) > 1 else 0.0
        if best_score < 0.75:
            return ("unknown", 0.0)
        if second_score and (best_score - second_score) < 0.15:
            return ("unknown", 0.0)
        return (best_type, best_score)

    def _detect_from_values(self, values: list[str]) -> tuple[str | None, float]:
        """Detect type from sample values.

        Args:
            values: Sample values.

        Returns:
            Tuple of (type, confidence).
        """
        if not values:
            return (None, 0.0)

        # Count matches for each pattern
        matches: dict[str, int] = {}
        total = len(values)

        for value in values:
            value = value.strip()
            if not value:
                continue

            for field_type, pattern in VALUE_PATTERNS.items():
                if pattern.match(value):
                    matches[field_type] = matches.get(field_type, 0) + 1

        # Find best match
        if not matches:
            return (None, 0.0)

        best_type = max(matches, key=lambda k: matches[k])
        confidence = matches[best_type] / total

        return (best_type, confidence)

    def _get_mapping(self, field_type: str) -> str | None:
        """Get suggested database field mapping.

        Args:
            field_type: Detected field type.

        Returns:
            Suggested database field name.
        """
        return FIELD_MAPPINGS.get(field_type)
