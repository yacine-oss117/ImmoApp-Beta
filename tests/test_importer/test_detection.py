"""
Comprehensive tests for detection and intelligence modules.

Tests cover:
- ColumnDetector: column type inference
- HeaderDetector: header row detection
- DuplicateDetector: duplicate row detection (intelligence layer)
- EntityTypeDetector: client vs listing detection
"""

from __future__ import annotations

import pytest

from core.importer.detection import ColumnDetector, EntityTypeDetector, HeaderDetector
from core.importer.intelligence import DuplicateDetector, DuplicateMatch

# =============================================================================
# DuplicateDetector Tests
# =============================================================================


class TestDuplicateDetector:
    """Tests for DuplicateDetector."""

    @pytest.fixture
    def detector(self) -> DuplicateDetector:
        """Create a duplicate detector instance."""
        return DuplicateDetector()

    def test_no_duplicates_in_unique_rows(self, detector: DuplicateDetector) -> None:
        """Rows with different phone numbers are not duplicates."""
        rows = [
            {"Nom": "Ahmed", "Phone": "0555111111"},
            {"Nom": "Karim", "Phone": "0555222222"},
            {"Nom": "Fatima", "Phone": "0555333333"},
        ]
        result = detector.detect(rows)

        assert not result.has_duplicates
        assert result.unique_count == 3
        assert result.duplicate_count == 0

    def test_exact_phone_duplicate(self, detector: DuplicateDetector) -> None:
        """Identical phone numbers are detected as duplicates."""
        rows = [
            {"Nom": "Ahmed", "Phone": "0555123456"},
            {"Nom": "Mohamed", "Phone": "0555123456"},  # Same phone
        ]
        result = detector.detect(rows)

        assert result.has_duplicates
        assert len(result.duplicates) == 1
        assert result.duplicates[0].row_index == 1
        assert result.duplicates[0].matched_row_index == 0
        assert result.duplicates[0].confidence >= 0.9

    def test_phone_with_different_formats(self, detector: DuplicateDetector) -> None:
        """Phone numbers with different formats are detected as same."""
        rows = [
            {"Nom": "Ahmed", "Phone": "0555123456"},
            {"Nom": "Ahmed", "Phone": "05 55 12 34 56"},  # Same phone, spaces
        ]
        result = detector.detect(rows)

        assert result.has_duplicates
        assert result.duplicates[0].confidence >= 0.9

    def test_phone_with_international_format(self, detector: DuplicateDetector) -> None:
        """International phone formats are normalized."""
        rows = [
            {"Nom": "Ahmed", "Tel": "0555123456"},
            {"Nom": "Ahmed Copy", "Tel": "+213555123456"},  # International format
        ]
        result = detector.detect(rows)

        assert result.has_duplicates
        assert result.duplicates[0].confidence >= 0.9

    def test_email_duplicate(self, detector: DuplicateDetector) -> None:
        """Identical emails are detected as duplicates."""
        rows = [
            {"Nom": "Ahmed", "Email": "ahmed@example.com"},
            {"Nom": "Ahmed Ben Ali", "Email": "ahmed@example.com"},
        ]
        result = detector.detect(rows)

        assert result.has_duplicates
        assert "email" in result.duplicates[0].matched_fields
        assert result.duplicates[0].confidence >= 1.0

    def test_multiple_duplicates(self, detector: DuplicateDetector) -> None:
        """Multiple duplicate rows are all detected."""
        rows = [
            {"Nom": "Ahmed", "Phone": "0555111111"},
            {"Nom": "Copy 1", "Phone": "0555111111"},
            {"Nom": "Copy 2", "Phone": "0555111111"},
        ]
        result = detector.detect(rows)

        # Row 1 matches 0, Row 2 matches both 0 and 1 = 3 total matches
        assert len(result.duplicates) >= 2
        assert result.duplicate_count == 2  # 2 rows are duplicates (1 and 2)
        assert result.unique_count == 1  # Only row 0 is unique

    def test_empty_rows(self, detector: DuplicateDetector) -> None:
        """Empty row list returns no duplicates."""
        result = detector.detect([])

        assert not result.has_duplicates
        assert result.unique_count == 0
        assert result.duplicate_count == 0

    def test_rows_without_key_fields(self, detector: DuplicateDetector) -> None:
        """Rows without phone/email don't produce duplicates."""
        rows = [
            {"Address": "123 Main St", "City": "Alger"},
            {"Address": "456 Oak Ave", "City": "Oran"},
        ]
        result = detector.detect(rows)

        assert not result.has_duplicates

    def test_name_match_lower_confidence(self, detector: DuplicateDetector) -> None:
        """Name-only matches have lower confidence than phone matches."""
        detector_with_names = DuplicateDetector(
            key_fields=["nom", "phone"],
            min_confidence=0.5,  # Accept lower confidence
        )
        rows = [
            {"Nom": "Ahmed", "Phone": "0555111111"},
            {"Nom": "Ahmed", "Phone": "0555222222"},  # Same name, different phone
        ]
        result = detector_with_names.detect(rows)

        if result.has_duplicates:
            # Name matches should have lower confidence than phone
            assert result.duplicates[0].confidence < 0.9

    def test_is_exact_match_property(self) -> None:
        """DuplicateMatch.is_exact_match returns True for confidence=1.0."""
        exact = DuplicateMatch(
            row_index=1,
            matched_row_index=0,
            matched_fields=["email"],
            confidence=1.0,
        )
        assert exact.is_exact_match

        fuzzy = DuplicateMatch(
            row_index=1,
            matched_row_index=0,
            matched_fields=["nom"],
            confidence=0.6,
        )
        assert not fuzzy.is_exact_match


class TestHeaderDetector:
    """Tests for HeaderDetector."""

    @pytest.fixture
    def detector(self) -> HeaderDetector:
        """Create a header detector instance."""
        return HeaderDetector()

    def test_detect_header_row_with_keywords(self, detector: HeaderDetector) -> None:
        """Rows with header keywords are detected as headers."""
        rows = [
            ["Nom", "Téléphone", "Budget", "Type"],
            ["Ahmed", "0555123456", "2M", "F3"],
        ]
        result = detector.detect_header(rows)

        assert result.has_header
        assert result.header_row_index == 0
        assert result.confidence >= 0.8

    def test_detect_no_header_when_first_row_is_data(self, detector: HeaderDetector) -> None:
        """Files starting with data rows are detected correctly."""
        rows = [
            ["Ahmed", "0555123456", "2500000", "Appartement"],
            ["Karim", "0661234567", "3000000", "Villa"],
        ]
        result = detector.detect_header(rows)

        # First row looks like data, not headers
        if result.has_header:
            assert result.confidence < 0.7  # Lower confidence

    def test_empty_rows_no_header(self, detector: HeaderDetector) -> None:
        """Empty row list has no header."""
        result = detector.detect_header([])
        assert not result.has_header

    def test_single_row_detected_as_header(self, detector: HeaderDetector) -> None:
        """Single row with header keywords is detected as header."""
        rows = [["Name", "Phone", "Email", "Budget"]]
        result = detector.detect_header(rows)

        assert result.has_header or result.confidence > 0.5


class TestColumnDetectorIntegration:
    """Integration tests for ColumnDetector with realistic data."""

    @pytest.fixture
    def detector(self) -> ColumnDetector:
        """Create a column detector instance."""
        return ColumnDetector()

    def test_detect_all_algerian_columns(self, detector: ColumnDetector) -> None:
        """Detect columns with Algerian-specific headers."""
        headers = ["Wilaya", "Commune", "Téléphone", "Budget", "Type Bien"]
        rows = [
            {
                "Wilaya": "Alger",
                "Commune": "Bab El Oued",
                "Téléphone": "0555123456",
                "Budget": "3M",
                "Type Bien": "F3",
            }
        ]

        results = detector.detect_all_columns(headers, rows)
        result_map = {r.column_name: r for r in results}

        assert result_map["Wilaya"].detected_type == "wilaya"
        assert result_map["Commune"].detected_type == "location"
        assert result_map["Téléphone"].detected_type == "phone"
        assert result_map["Budget"].detected_type == "price"
        assert result_map["Type Bien"].detected_type == "type"

    def test_detect_arabic_headers(self, detector: ColumnDetector) -> None:
        """Detect columns with Arabic headers."""
        headers = ["هاتف", "ميزانية", "ولاية"]
        rows = [{"هاتف": "0555123456", "ميزانية": "2M", "ولاية": "الجزائر"}]

        results = detector.detect_all_columns(headers, rows)
        result_map = {r.column_name: r for r in results}

        assert result_map["هاتف"].detected_type == "phone"
        assert result_map["ميزانية"].detected_type == "price"
        assert result_map["ولاية"].detected_type == "wilaya"


# =============================================================================
# ODS Parser Tests
# =============================================================================


class TestOdsParserIntegration:
    """Integration tests for ODS parser."""

    def test_ods_parser_can_parse_extension(self) -> None:
        """ODS parser recognizes .ods extension."""
        from pathlib import Path

        from core.importer.parsers import OdsParser

        parser = OdsParser()
        assert parser.can_parse(Path("test.ods"))
        assert not parser.can_parse(Path("test.xlsx"))
        assert not parser.can_parse(Path("test.csv"))


# =============================================================================
# EntityTypeDetector Tests
# =============================================================================


class TestEntityTypeDetector:
    """Tests for EntityTypeDetector."""

    @pytest.fixture
    def detector(self) -> EntityTypeDetector:
        """Create an entity type detector instance."""
        from core.importer.detection import EntityTypeDetector

        return EntityTypeDetector()

    def test_detect_client_columns(self, detector: EntityTypeDetector) -> None:
        """Columns with phone/budget indicate client data."""
        from core.importer.detection import EntityTypeDetector

        detector = EntityTypeDetector()
        columns = ["Nom", "Téléphone", "Budget", "Type"]
        result = detector.detect(columns)

        assert result.entity_type == "client"
        assert result.confidence > 0.5
        assert result.client_score >= 2

    def test_detect_listing_columns(self, detector: EntityTypeDetector) -> None:
        """Columns with surface/prix/etage indicate listing data."""
        from core.importer.detection import EntityTypeDetector

        detector = EntityTypeDetector()
        columns = ["Surface", "Prix", "Étage", "Pièces", "Type"]
        result = detector.detect(columns)

        assert result.entity_type == "listing"
        assert result.confidence > 0.5
        assert result.listing_score >= 3

    def test_detect_ambiguous_columns(self, detector: EntityTypeDetector) -> None:
        """Columns with equal indicators are ambiguous."""
        from core.importer.detection import EntityTypeDetector

        detector = EntityTypeDetector()
        columns = ["Type", "Location"]  # No clear indicators
        result = detector.detect(columns)

        # Should be uncertain
        assert result.confidence <= 0.5 or result.entity_type is None

    def test_detect_empty_columns(self, detector: EntityTypeDetector) -> None:
        """Empty columns return no entity type."""
        from core.importer.detection import EntityTypeDetector

        detector = EntityTypeDetector()
        result = detector.detect([])

        assert result.entity_type is None
        assert result.confidence == 0.0

    def test_backwards_compatible_function(self) -> None:
        """detect_entity_type_from_columns returns tuple."""
        from core.importer.detection import detect_entity_type_from_columns

        entity_type, confidence = detect_entity_type_from_columns(["Nom", "Téléphone", "Budget"])

        assert entity_type == "client"
        assert confidence > 0.5

    def test_word_boundaries_avoid_autonome_false_positive(self) -> None:
        detector = EntityTypeDetector()
        result = detector.detect(["Autonome", "Reference"])

        assert result.entity_type == "listing"
        assert result.client_score == 0

    def test_underscore_delimited_headers_are_detected(self) -> None:
        detector = EntityTypeDetector()
        result = detector.detect(["prix_de_vente", "surface_m2"])

        assert result.entity_type == "listing"
        assert result.listing_score >= 2
