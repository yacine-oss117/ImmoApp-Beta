"""Unit tests for location normalization."""

from __future__ import annotations

import pytest

from core.importer.normalizers.base import RowContext
from core.importer.normalizers.location import LocationNormalizer


class TestLocationNormalizer:
    """Tests for LocationNormalizer."""

    @pytest.fixture
    def normalizer(self) -> LocationNormalizer:
        """Create location normalizer instance."""
        return LocationNormalizer()

    def test_empty_value(self, normalizer: LocationNormalizer) -> None:
        """Test empty value returns None."""
        result = normalizer.normalize("")
        assert result.value is None
        assert result.confidence == 1.0

    def test_exact_commune_match(self, normalizer: LocationNormalizer) -> None:
        """Test exact commune name match."""
        result = normalizer.normalize("Hydra")
        assert result.value == "16028"
        assert result.confidence == 1.0
        assert result.extracted_extras.get("match_type") in ("exact_commune", "alias")

    def test_commune_with_accents(self, normalizer: LocationNormalizer) -> None:
        """Test commune name with accents."""
        result = normalizer.normalize("Béjaïa")
        assert result.value == "06001"
        assert result.confidence >= 0.9

    def test_commune_lowercase(self, normalizer: LocationNormalizer) -> None:
        """Test lowercase commune name."""
        result = normalizer.normalize("cheraga")
        assert result.value == "16050"
        assert result.confidence == 1.0

    def test_commune_alias(self, normalizer: LocationNormalizer) -> None:
        """Test commune alias match."""
        result = normalizer.normalize("guyotville")
        assert result.value == "16044"
        assert result.confidence == 1.0

    def test_wilaya_match(self, normalizer: LocationNormalizer) -> None:
        """Test wilaya name match."""
        result = normalizer.normalize("Alger")
        assert result.value == "16"
        assert result.confidence == 0.9
        assert result.extracted_extras.get("is_wilaya") is True

    def test_wilaya_arabic(self, normalizer: LocationNormalizer) -> None:
        """Test wilaya Arabic name match."""
        result = normalizer.normalize("الجزائر")
        assert result.value == "16"

    def test_unknown_location(self, normalizer: LocationNormalizer) -> None:
        """Test unknown location returns None."""
        result = normalizer.normalize("XYZ123Unknown")
        assert result.value is None
        assert result.confidence == 0.0
        assert result.needs_review is True

    def test_get_wilaya_name(self, normalizer: LocationNormalizer) -> None:
        """Test get wilaya name by code."""
        assert normalizer.get_wilaya_name("16") == "Alger"
        assert normalizer.get_wilaya_name("31") == "Oran"
        assert normalizer.get_wilaya_name("99") is None

    def test_get_commune_name(self, normalizer: LocationNormalizer) -> None:
        """Test get commune name by code."""
        assert normalizer.get_commune_name("16028") == "Hydra"
        assert normalizer.get_commune_name("16050") == "Cheraga"
        assert normalizer.get_commune_name("99999") is None

    def test_wilaya_context_hint(self, normalizer: LocationNormalizer) -> None:
        """Test wilaya hint in context."""
        context = RowContext(wilaya_hint="16")
        result = normalizer.normalize("Hydra", context)
        assert result.value == "16028"
        assert result.confidence == 1.0


class TestLocationNormalizerEdgeCases:
    """Edge case tests for location normalization."""

    @pytest.fixture
    def normalizer(self) -> LocationNormalizer:
        return LocationNormalizer()

    def test_mixed_french_arabic(self, normalizer: LocationNormalizer) -> None:
        """Test mixed French and Arabic in same input."""
        result = normalizer.normalize("Hydra الحيدرة")
        assert result.value is not None

    def test_location_with_postal_code(self, normalizer: LocationNormalizer) -> None:
        """Test location with postal code."""
        result = normalizer.normalize("16028 Hydra")
        assert result.value is not None

    def test_location_all_caps(self, normalizer: LocationNormalizer) -> None:
        """Test ALL CAPS location."""
        result = normalizer.normalize("CHERAGA")
        assert result.value == "16050"

    def test_location_mixed_case(self, normalizer: LocationNormalizer) -> None:
        """Test mixed case location."""
        result = normalizer.normalize("cHeRaGa")
        assert result.value == "16050"

    def test_location_with_comma(self, normalizer: LocationNormalizer) -> None:
        """Test location with extra info after comma."""
        result = normalizer.normalize("Hydra, Alger")
        assert result.value is not None

    def test_location_with_parentheses(self, normalizer: LocationNormalizer) -> None:
        """Test location with parenthetical info."""
        result = normalizer.normalize("Hydra (Alger)")
        assert result.value is not None

    def test_common_typo_hyra(self, normalizer: LocationNormalizer) -> None:
        """Test common misspelling of Hydra."""
        result = normalizer.normalize("hyra")
        assert result.needs_review or result.value is not None

    def test_arabic_only_location(self, normalizer: LocationNormalizer) -> None:
        """Test pure Arabic location name."""
        result = normalizer.normalize("الشراقة")
        assert result.value == "16050"

    def test_empty_string(self, normalizer: LocationNormalizer) -> None:
        """Test empty string."""
        result = normalizer.normalize("")
        assert result.value is None

    def test_whitespace_only(self, normalizer: LocationNormalizer) -> None:
        """Test whitespace only."""
        result = normalizer.normalize("   ")
        assert result.value is None
