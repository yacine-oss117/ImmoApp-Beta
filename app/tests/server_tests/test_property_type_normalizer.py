"""Tests for PropertyTypeNormalizer."""

from __future__ import annotations

import pytest

from core.importer.normalizers.property_type import PropertyTypeNormalizer


@pytest.fixture
def normalizer() -> PropertyTypeNormalizer:
    return PropertyTypeNormalizer()


class TestPropertyTypeNormalizer:
    """Test property type normalization with bed extraction."""

    def test_f3_apartment(self, normalizer: PropertyTypeNormalizer) -> None:
        """F3 should be recognized as apartment with 3 beds."""
        result = normalizer.normalize("F3")
        assert result.value is not None
        assert result.confidence >= 0.9
        # Should extract beds
        assert result.extracted_extras.get("beds") == 3 or "3" in str(result.value)

    def test_f4(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("F4")
        assert result.value is not None
        assert result.confidence >= 0.9

    def test_villa(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("Villa")
        assert result.value is not None
        assert result.confidence >= 0.9

    def test_appartement_french(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("Appartement")
        assert result.value is not None
        assert result.confidence >= 0.9

    def test_typo_appartment(self, normalizer: PropertyTypeNormalizer) -> None:
        """Common English typo should still match."""
        result = normalizer.normalize("appartment")
        assert result.value is not None

    def test_studio(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("Studio")
        assert result.value is not None
        assert result.confidence >= 0.9

    def test_duplex(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("Duplex")
        assert result.value is not None

    def test_terrain(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("Terrain")
        assert result.value is not None

    def test_arabic_apartment(self, normalizer: PropertyTypeNormalizer) -> None:
        """Arabic شقة should be recognized."""
        result = normalizer.normalize("شقة")
        assert result.value is not None

    def test_arabic_villa(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("فيلا")
        assert result.value is not None

    def test_unknown_type(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("XYZXYZ_UNKNOWN_TYPE")
        assert result.needs_review or result.confidence < 0.5

    def test_empty(self, normalizer: PropertyTypeNormalizer) -> None:
        result = normalizer.normalize("")
        assert result.value is None or result.value == ""

    def test_case_insensitive(self, normalizer: PropertyTypeNormalizer) -> None:
        r1 = normalizer.normalize("VILLA")
        r2 = normalizer.normalize("villa")
        assert r1.value == r2.value

    def test_combined_type_and_rooms(self, normalizer: PropertyTypeNormalizer) -> None:
        """F3 Duplex or similar combined string."""
        result = normalizer.normalize("F3 Duplex")
        assert result.value is not None
