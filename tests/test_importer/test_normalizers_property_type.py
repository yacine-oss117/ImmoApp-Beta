"""Unit tests for property type normalization."""

from __future__ import annotations

import pytest

from core.importer.normalizers.property_type import PropertyTypeNormalizer


class TestPropertyTypeNormalizer:
    """Tests for PropertyTypeNormalizer."""

    @pytest.fixture
    def normalizer(self) -> PropertyTypeNormalizer:
        """Create property type normalizer instance."""
        return PropertyTypeNormalizer()

    def test_empty_value(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test empty value returns None."""
        result = normalizer.normalize("")
        assert result.value is None
        assert result.confidence == 1.0

    def test_f3_format(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test F3 format extraction."""
        result = normalizer.normalize("F3")
        assert result.value == "apartment"
        assert result.confidence == 1.0
        assert result.extracted_extras.get("beds") == 3

    def test_f4_lowercase(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test f4 lowercase."""
        result = normalizer.normalize("f4")
        assert result.value == "apartment"
        assert result.extracted_extras.get("beds") == 4

    def test_villa(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test villa type."""
        result = normalizer.normalize("Villa")
        assert result.value == "villa"
        assert result.confidence == 1.0

    def test_studio(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test studio type (default 1 bed)."""
        result = normalizer.normalize("Studio")
        assert result.value == "studio"
        assert result.extracted_extras.get("beds") == 1

    def test_appartement(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test French appartement."""
        result = normalizer.normalize("Appartement")
        assert result.value == "apartment"

    def test_apartment_with_beds(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test apartment with bedroom count."""
        result = normalizer.normalize("Appartement 3 chambres")
        assert result.value == "apartment"
        assert result.extracted_extras.get("beds") == 3

    def test_local_commercial(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test commercial property."""
        result = normalizer.normalize("Local commercial")
        assert result.value == "commercial"

    def test_terrain(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test land type."""
        result = normalizer.normalize("Terrain")
        assert result.value == "land"

    def test_duplex(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test duplex type."""
        result = normalizer.normalize("Duplex")
        assert result.value == "duplex"

    def test_unknown_type(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test unknown type."""
        result = normalizer.normalize("XYZUnknown")
        assert result.value is None
        assert result.confidence == 0.0
        assert result.needs_review is True

    def test_get_type_display(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test display name."""
        assert normalizer.get_type_display("apartment") == "Appartement"
        assert normalizer.get_type_display("villa") == "Villa"
        assert normalizer.get_type_display("land") == "Terrain"


class TestPropertyTypeEdgeCases:
    """Edge case tests for property type normalization."""

    @pytest.fixture
    def normalizer(self) -> PropertyTypeNormalizer:
        return PropertyTypeNormalizer()

    def test_apartment_arabic(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test Arabic word for apartment."""
        result = normalizer.normalize("شقة")
        assert result.value == "apartment" or result.needs_review

    def test_property_with_f_notation(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test French F3 notation (3 rooms)."""
        result = normalizer.normalize("F3")
        assert result.value == "apartment"
        assert result.extracted_extras.get("beds") == 3

    def test_property_with_f_notation_large(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test large F notation."""
        result = normalizer.normalize("F7")
        assert result.value == "apartment"

    def test_studio_variations(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test studio apartment variations."""
        for term in ["Studio", "STUDIO", "studio", "F1"]:
            result = normalizer.normalize(term)
            assert result.value in ("apartment", "studio")

    def test_type_with_surface(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test property type with surface area."""
        result = normalizer.normalize("Appartement 120m²")
        assert result.value == "apartment"

    def test_type_abbreviations(self, normalizer: PropertyTypeNormalizer) -> None:
        """Test common abbreviations."""
        result = normalizer.normalize("Appt")
        assert result.value == "apartment" or result.needs_review

    def test_local_commercial_matches_before_local(
        self, normalizer: PropertyTypeNormalizer
    ) -> None:
        result = normalizer.normalize("local commercial")
        assert result.value == "commercial"

    def test_bureau_not_confused_with_other_substrings(
        self, normalizer: PropertyTypeNormalizer
    ) -> None:
        result = normalizer.normalize("bureau")
        assert result.value == "office"

    def test_parking_en_sous_sol(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("parking en sous sol")
        assert result.value in ("parking", "basement")
