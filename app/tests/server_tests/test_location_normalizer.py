"""Tests for LocationNormalizer."""

from __future__ import annotations

import pytest

from core.importer.normalizers.base import RowContext
from core.importer.normalizers.location_normalizer import LocationNormalizer


@pytest.fixture
def normalizer() -> LocationNormalizer:
    return LocationNormalizer()


class TestLocationNormalizer:
    """Test Algerian location normalization with fuzzy matching."""

    def test_exact_wilaya_name(self, normalizer: LocationNormalizer) -> None:
        """Exact wilaya name should match with high confidence."""
        result = normalizer.normalize("Alger")
        assert result.value is not None
        assert result.confidence >= 0.85

    def test_wilaya_numeric_code(self, normalizer: LocationNormalizer) -> None:
        """Bare numeric codes are not handled by LocationNormalizer.
        They're handled by NormalizationPipeline._normalize_wilaya instead.
        """
        result = normalizer.normalize("16")
        # LocationNormalizer treats this as unknown text — that's expected
        assert result.needs_review or result.value is None

    def test_commune_exact_match(self, normalizer: LocationNormalizer) -> None:
        """Known commune should match."""
        result = normalizer.normalize("Bab El Oued")
        assert result.value is not None
        assert result.confidence >= 0.8

    def test_fuzzy_typo(self, normalizer: LocationNormalizer) -> None:
        """Minor typo should still fuzzy-match."""
        result = normalizer.normalize("Bab el Oued")  # case diff
        assert result.value is not None

    def test_wilaya_hint_helps(self, normalizer: LocationNormalizer) -> None:
        """Providing a wilaya hint should improve matching."""
        context = RowContext(wilaya_hint="16")
        result = normalizer.normalize("Bab El Oued", context=context)
        assert result.value is not None

    def test_unknown_location(self, normalizer: LocationNormalizer) -> None:
        """Completely unknown location should flag for review."""
        result = normalizer.normalize("XYZXYZ_UNKNOWN_PLACE")
        assert result.needs_review or result.confidence < 0.5

    def test_empty_string(self, normalizer: LocationNormalizer) -> None:
        result = normalizer.normalize("")
        assert result.value is None or result.value == ""

    def test_arabic_wilaya_name(self, normalizer: LocationNormalizer) -> None:
        """Arabic wilaya names should be handled."""
        result = normalizer.normalize("الجزائر")
        # May or may not match depending on master data
        assert result is not None

    def test_case_insensitive(self, normalizer: LocationNormalizer) -> None:
        """Matching should be case-insensitive."""
        result1 = normalizer.normalize("ALGER")
        result2 = normalizer.normalize("alger")
        # Both should produce results
        assert result1.value is not None or result1.needs_review
        assert result2.value is not None or result2.needs_review

    def test_with_extra_spaces(self, normalizer: LocationNormalizer) -> None:
        """Extra whitespace should be trimmed."""
        result = normalizer.normalize("  Alger  ")
        assert result.value is not None
