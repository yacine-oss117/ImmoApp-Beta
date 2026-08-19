"""Unit tests for phone normalization."""

from __future__ import annotations

import pytest

from core.importer.normalizers.phone import PhoneNormalizer


class TestPhoneNormalizer:
    """Tests for PhoneNormalizer."""

    @pytest.fixture
    def normalizer(self) -> PhoneNormalizer:
        """Create phone normalizer instance."""
        return PhoneNormalizer()

    def test_empty_value(self, normalizer: PhoneNormalizer) -> None:
        """Test empty value returns None."""
        result = normalizer.normalize("")
        assert result.value is None
        assert result.confidence == 1.0

    def test_standard_format(self, normalizer: PhoneNormalizer) -> None:
        """Test standard 10-digit format."""
        result = normalizer.normalize("0555123456")
        assert result.value == "0555123456"
        assert result.confidence == 1.0
        assert result.needs_review is False

    def test_spaced_format(self, normalizer: PhoneNormalizer) -> None:
        """Test phone with spaces."""
        result = normalizer.normalize("05 55 12 34 56")
        assert result.value == "0555123456"
        assert result.confidence == 1.0

    def test_dashed_format(self, normalizer: PhoneNormalizer) -> None:
        """Test phone with dashes."""
        result = normalizer.normalize("05-55-12-34-56")
        assert result.value == "0555123456"
        assert result.confidence == 1.0

    def test_international_plus213(self, normalizer: PhoneNormalizer) -> None:
        """Test international format with +213."""
        result = normalizer.normalize("+213 555 123 456")
        assert result.value == "0555123456"
        assert result.confidence == 1.0

    def test_international_00213(self, normalizer: PhoneNormalizer) -> None:
        """Test international format with 00213."""
        result = normalizer.normalize("00213555123456")
        assert result.value == "0555123456"
        assert result.confidence == 1.0

    def test_missing_leading_zero(self, normalizer: PhoneNormalizer) -> None:
        """Test 9-digit number missing leading zero."""
        result = normalizer.normalize("555123456")
        assert result.value == "0555123456"
        assert result.confidence == 1.0

    def test_mobile_prefixes(self, normalizer: PhoneNormalizer) -> None:
        """Test all mobile prefixes are valid."""
        for prefix in ["05", "06", "07"]:
            result = normalizer.normalize(f"{prefix}55123456")
            assert result.confidence == 1.0, f"Prefix {prefix} should be valid"

    def test_landline_prefixes(self, normalizer: PhoneNormalizer) -> None:
        """Test landline prefixes are valid."""
        for prefix in ["02", "03", "04"]:
            result = normalizer.normalize(f"{prefix}12345678")
            assert result.confidence == 1.0, f"Prefix {prefix} should be valid"

    def test_invalid_prefix(self, normalizer: PhoneNormalizer) -> None:
        """08 service numbers should be accepted and typed."""
        result = normalizer.normalize("0855123456")
        assert result.value == "0855123456"
        assert result.confidence == 0.95
        assert result.needs_review is False
        assert result.extracted_extras["phone_kind"] == "service"

    def test_special_prefix_09_is_valid(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("0955123456")
        assert result.value == "0955123456"
        assert result.confidence == 0.95
        assert result.needs_review is False
        assert result.extracted_extras["phone_kind"] == "special"

    def test_too_short(self, normalizer: PhoneNormalizer) -> None:
        """Test too short number triggers review."""
        result = normalizer.normalize("05551234")
        assert result.confidence == 0.3
        assert result.needs_review is True
        assert result.value is None

    def test_too_long(self, normalizer: PhoneNormalizer) -> None:
        """Test too long number triggers review."""
        result = normalizer.normalize("055512345678")
        assert result.confidence == 0.3
        assert result.needs_review is True
        assert result.value is None

    def test_spelled_partial_phone_fragment_does_not_become_fake_identity(
        self, normalizer: PhoneNormalizer
    ) -> None:
        result = normalizer.normalize("zero six 66")
        assert result.value is None
        assert result.confidence == 0.3
        assert result.needs_review is True

    def test_format_display(self, normalizer: PhoneNormalizer) -> None:
        """Test display formatting."""
        formatted = normalizer.format_display("0555123456")
        assert formatted == "05 55 12 34 56"

    def test_format_international(self, normalizer: PhoneNormalizer) -> None:
        """Test international formatting."""
        formatted = normalizer.format_international("0555123456")
        assert formatted == "+213 555 123 456"

    def test_parentheses_removed(self, normalizer: PhoneNormalizer) -> None:
        """Test parentheses are removed."""
        result = normalizer.normalize("(05) 55 12 34 56")
        assert result.value == "0555123456"


class TestPhoneNormalizerEdgeCases:
    """Edge case tests for phone normalization."""

    @pytest.fixture
    def normalizer(self) -> PhoneNormalizer:
        return PhoneNormalizer()

    def test_arabic_numerals(self, normalizer: PhoneNormalizer) -> None:
        """Test Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩)."""
        result = normalizer.normalize("٠٥٥١٢٣٤٥٦٧")
        assert result.value == "0551234567"
        assert result.needs_review is False

    def test_mixed_arabic_latin_numbers(self, normalizer: PhoneNormalizer) -> None:
        """Test mixed Arabic and Latin numerals."""
        result = normalizer.normalize("05٥١234567")
        assert result.value == "0551234567"
        assert result.needs_review is False

    def test_phone_with_newlines(self, normalizer: PhoneNormalizer) -> None:
        """Test phone number with embedded newlines."""
        result = normalizer.normalize("0551\n234567")
        assert result.value == "0551234567"

    def test_phone_with_tabs(self, normalizer: PhoneNormalizer) -> None:
        """Test phone number with tabs."""
        result = normalizer.normalize("0551\t234\t567")
        assert result.value == "0551234567"

    def test_phone_with_non_breaking_space(self, normalizer: PhoneNormalizer) -> None:
        """Test phone with non-breaking space (\xa0)."""
        result = normalizer.normalize("0551\xa0234\xa0567")
        assert result.value == "0551234567"

    def test_phone_with_leading_trailing_spaces(self, normalizer: PhoneNormalizer) -> None:
        """Test phone with lots of whitespace."""
        result = normalizer.normalize("   0551234567   ")
        assert result.value == "0551234567"

    def test_phone_all_zeros(self, normalizer: PhoneNormalizer) -> None:
        """Test phone that's all zeros."""
        result = normalizer.normalize("0000000000")
        assert result.needs_review or result.confidence < 0.9

    def test_phone_repeated_digits(self, normalizer: PhoneNormalizer) -> None:
        """Test phone with repeated digits (likely fake)."""
        result = normalizer.normalize("0555555555")
        assert result.value == "0555555555"

    def test_phone_with_plus_sign_variations(self, normalizer: PhoneNormalizer) -> None:
        """Test various plus sign representations."""
        result = normalizer.normalize("＋213551234567")
        assert result.value == "0551234567"
        assert result.needs_review is False
