"""Tests for DuplicateDetector (within-file dedup)."""

from __future__ import annotations

import pytest

from core.importer.intelligence.conflict_resolver import (
    DuplicateDetector,
)


@pytest.fixture
def detector() -> DuplicateDetector:
    return DuplicateDetector(key_fields=["phone", "email"])


class TestDuplicateDetector:
    """Test within-file duplicate detection."""

    def test_no_duplicates(self, detector: DuplicateDetector) -> None:
        rows = [
            {"phone": "0555111111", "name": "Ali"},
            {"phone": "0555222222", "name": "Omar"},
            {"phone": "0555333333", "name": "Karim"},
        ]
        result = detector.detect(rows)
        assert not result.has_duplicates
        assert result.unique_count == 3
        assert result.duplicate_count == 0

    def test_phone_duplicates(self, detector: DuplicateDetector) -> None:
        rows = [
            {"phone": "0555123456", "name": "Ali"},
            {"phone": "0666789012", "name": "Omar"},
            {"phone": "0555123456", "name": "Ali (dup)"},
        ]
        result = detector.detect(rows)
        assert result.has_duplicates
        assert result.duplicate_count >= 1
        # Row 2 (index=2) should match row 0 (index=0)
        dup = result.duplicates[0]
        assert dup.row_index == 2
        assert dup.matched_row_index == 0

    def test_email_duplicates(self, detector: DuplicateDetector) -> None:
        rows = [
            {"email": "ali@test.com", "name": "Ali"},
            {"email": "omar@test.com", "name": "Omar"},
            {"email": "ali@test.com", "name": "Ali Copy"},
        ]
        result = detector.detect(rows)
        assert result.has_duplicates

    def test_algerian_phone_prefix_normalization(self, detector: DuplicateDetector) -> None:
        """Different Algerian prefixes for the same number should match."""
        rows = [
            {"phone": "0555123456"},
            {"phone": "+213555123456"},  # International
        ]
        result = detector.detect(rows)
        assert result.has_duplicates

    def test_empty_rows(self, detector: DuplicateDetector) -> None:
        result = detector.detect([])
        assert not result.has_duplicates
        assert result.unique_count == 0

    def test_single_row(self, detector: DuplicateDetector) -> None:
        result = detector.detect([{"phone": "0555123456"}])
        assert not result.has_duplicates
        assert result.unique_count == 1

    def test_empty_phone_not_duplicate(self, detector: DuplicateDetector) -> None:
        """Rows with no phone should not match each other."""
        rows = [
            {"name": "Ali"},
            {"name": "Omar"},
        ]
        result = detector.detect(rows)
        assert not result.has_duplicates

    def test_confidence_phone_high(self, detector: DuplicateDetector) -> None:
        """Phone matches should have high confidence."""
        rows = [
            {"phone": "0555123456"},
            {"phone": "0555123456"},
        ]
        result = detector.detect(rows)
        assert result.duplicates[0].confidence >= 0.9

    def test_multiple_duplicates(self, detector: DuplicateDetector) -> None:
        """Multiple rows with same phone."""
        rows = [
            {"phone": "0555123456"},
            {"phone": "0555123456"},
            {"phone": "0555123456"},
        ]
        result = detector.detect(rows)
        assert result.duplicate_count >= 2

    def test_name_only_low_confidence(self) -> None:
        """Name-only matches should have lower confidence."""
        detector = DuplicateDetector(key_fields=["name"], min_confidence=0.5)
        rows = [
            {"name": "Ali Boumediene"},
            {"name": "Ali Boumediene"},
        ]
        result = detector.detect(rows)
        if result.has_duplicates:
            assert result.duplicates[0].confidence <= 0.7
