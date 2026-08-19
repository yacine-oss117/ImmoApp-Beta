"""
Header row detector.

Detects if a file's first row contains headers or data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.importer.detection.header_detector_rules import DATA_PATTERNS, HEADER_KEYWORDS


@dataclass
class HeaderDetectionResult:
    """Result of header detection.

    Attributes:
        has_header: Whether first row appears to be a header.
        confidence: Confidence score 0.0-1.0.
        header_row_index: Index of the header row (usually 0).
        reasons: Reasons for the detection.
    """

    has_header: bool
    confidence: float
    header_row_index: int = 0
    reasons: list[str] | None = None


class HeaderDetector:
    """Detects if a file has a header row.

    Uses heuristics like:
    - Presence of known header keywords
    - All-text first row followed by mixed content
    - Distinct patterns between first row and subsequent rows
    """

    def detect_header(
        self,
        rows: list[list[str]] | list[dict[str, str]],
    ) -> HeaderDetectionResult:
        """Detect if first row is a header.

        Args:
            rows: List of rows (either as lists or dicts).

        Returns:
            HeaderDetectionResult with detection info.
        """
        if not rows:
            return HeaderDetectionResult(
                has_header=False,
                confidence=0.0,
                reasons=["No rows provided"],
            )

        # Convert to list of lists if needed
        if isinstance(rows[0], dict):
            # If already dict, headers are keys - definitely has header
            return HeaderDetectionResult(
                has_header=True,
                confidence=1.0,
                reasons=["Data already has named columns"],
            )

        first_row = rows[0]
        reasons: list[str] = []

        # Check 1: Header keywords
        keyword_score = self._check_header_keywords(first_row)
        if keyword_score > 0.5:
            reasons.append(f"Header keywords found (score: {keyword_score:.0%})")

        # Check 2: Data patterns in first row (negative indicator)
        data_score = self._check_data_patterns(first_row)
        if data_score > 0.5:
            reasons.append(f"First row looks like data (score: {data_score:.0%})")

        # Check 3: Compare first row to other rows
        type_diff_score = 0.0
        if len(rows) > 1:
            rows_as_lists: list[list[str]] = rows
            type_diff_score = self._compare_row_types(first_row, rows_as_lists[1:5])
            if type_diff_score > 0.5:
                reasons.append(f"First row differs from data rows (score: {type_diff_score:.0%})")

        # Combine scores
        header_score = keyword_score + type_diff_score - data_score
        has_header = header_score > 0.3
        confidence = min(1.0, max(0.0, abs(header_score)))

        return HeaderDetectionResult(
            has_header=has_header,
            confidence=confidence,
            header_row_index=0 if has_header else -1,
            reasons=reasons,
        )

    def find_header_row(
        self,
        rows: list[list[str]],
        max_search: int = 5,
    ) -> int:
        """Find which row contains the header.

        Some files have empty rows or title rows before the actual header.

        Args:
            rows: List of rows.
            max_search: Maximum rows to search.

        Returns:
            Index of header row, or -1 if not found.
        """
        for i, row in enumerate(rows[:max_search]):
            # Skip empty or mostly empty rows
            non_empty = [cell for cell in row if cell and cell.strip()]
            if len(non_empty) < len(row) * 0.3:
                continue

            # Check if this row looks like a header
            result = self.detect_header([row])
            if result.has_header and result.confidence > 0.5:
                return i

        return 0  # Default to first row

    def _check_header_keywords(self, row: list[str]) -> float:
        """Check for header keywords in row.

        Args:
            row: Row cells.

        Returns:
            Score 0.0-1.0 indicating header likelihood.
        """
        if not row:
            return 0.0

        matches: float = 0.0
        for cell in row:
            cell_lower = cell.lower().strip()
            if cell_lower in HEADER_KEYWORDS:
                matches += 1.0
            else:
                # Partial match
                for keyword in HEADER_KEYWORDS:
                    if keyword in cell_lower or cell_lower in keyword:
                        matches += 0.5
                        break

        return min(1.0, matches / len(row))

    def _check_data_patterns(self, row: list[str]) -> float:
        """Check for data patterns in row.

        Args:
            row: Row cells.

        Returns:
            Score 0.0-1.0 indicating data likelihood.
        """
        if not row:
            return 0.0

        matches = 0
        for cell in row:
            cell = cell.strip()
            if not cell:
                continue

            for pattern in DATA_PATTERNS:
                if pattern.match(cell):
                    matches += 1
                    break

        return matches / len(row) if row else 0.0

    def _compare_row_types(
        self,
        first_row: list[str],
        other_rows: list[list[str]],
    ) -> float:
        """Compare first row type profile to other rows.

        Args:
            first_row: First row cells.
            other_rows: Other rows to compare.

        Returns:
            Score indicating how different first row is.
        """
        if not other_rows:
            return 0.0

        first_profile = self._get_type_profile(first_row)
        other_profiles = [self._get_type_profile(row) for row in other_rows]

        # Calculate difference
        differences = 0
        for i, first_type in enumerate(first_profile):
            if i >= len(other_profiles[0]):
                continue

            # Check if first row type differs from majority of other rows
            other_types = [p[i] if i < len(p) else "unknown" for p in other_profiles]
            most_common = max(set(other_types), key=other_types.count)

            if first_type != most_common:
                differences += 1

        return differences / len(first_profile) if first_profile else 0.0

    def _get_type_profile(self, row: list[str]) -> list[str]:
        """Get type profile for a row.

        Args:
            row: Row cells.

        Returns:
            List of type strings for each cell.
        """
        profile = []
        for cell in row:
            cell = str(cell).strip()
            if not cell:
                profile.append("empty")
            elif cell.isdigit():
                profile.append("number")
            elif re.match(r"^\d+[\.,]\d+$", cell):
                profile.append("decimal")
            elif re.match(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$", cell):
                profile.append("date")
            else:
                profile.append("text")
        return profile
