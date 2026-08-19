"""Tests for PhoneNormalizer."""

from __future__ import annotations

import pytest

from core.importer.normalizers.phone import PhoneNormalizer


@pytest.fixture
def normalizer() -> PhoneNormalizer:
    return PhoneNormalizer()


class TestPhoneNormalizer:
    """Test Algerian phone number normalization."""

    def test_standard_10_digit(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("0555123456")
        assert result.value == "0555123456"
        assert result.confidence >= 0.9

    def test_spaced_format(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("05 55 12 34 56")
        assert result.value == "0555123456"
        assert result.confidence >= 0.9

    def test_dotted_format(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("05.55.12.34.56")
        assert result.value == "0555123456"

    def test_dashed_format(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("05-55-12-34-56")
        assert result.value == "0555123456"

    def test_international_plus213(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("+213 555 123 456")
        assert result.value == "0555123456"
        assert result.confidence >= 0.9

    def test_double_zero_213(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("00213555123456")
        assert result.value == "0555123456"

    def test_missing_leading_zero(self, normalizer: PhoneNormalizer) -> None:
        """9-digit number starting with 5/6/7 should get 0 prepended."""
        result = normalizer.normalize("555123456")
        assert result.value == "0555123456"

    def test_arabic_indic_digits(self, normalizer: PhoneNormalizer) -> None:
        """Arabic-Indic numerals (٠-٩) should be converted."""
        result = normalizer.normalize("٠٥٥٥١٢٣٤٥٦")
        assert result.value == "0555123456"

    def test_mobile_prefix_06(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("0655123456")
        assert result.value == "0655123456"
        assert result.confidence >= 0.9

    def test_mobile_prefix_07(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("0770123456")
        assert result.value == "0770123456"

    def test_landline_prefix(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("0213456789")
        assert result.value is not None

    def test_service_prefix_08(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("0800123456")
        assert result.value == "0800123456"
        assert result.needs_review is False
        assert result.extracted_extras["phone_kind"] == "service"

    def test_special_prefix_09(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("0912345678")
        assert result.value == "0912345678"
        assert result.needs_review is False
        assert result.extracted_extras["phone_kind"] == "special"

    def test_empty_string(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("")
        assert result.value is None or result.value == ""

    def test_none_like(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("   ")
        assert result.value is None or result.value == ""

    def test_too_short(self, normalizer: PhoneNormalizer) -> None:
        """Very short input should flag for review."""
        result = normalizer.normalize("0555")
        assert result.needs_review or result.confidence < 0.85
        assert result.value is None

    def test_parenthesized_prefix(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("(0)555 123 456")
        # Should strip the (0) and normalize
        digits = "".join(c for c in str(result.value) if c.isdigit())
        assert len(digits) >= 9

    def test_with_text(self, normalizer: PhoneNormalizer) -> None:
        """Phone with text should still be handled."""
        result = normalizer.normalize("Tel: 0555123456")
        # May need review or extract the number
        assert result.value is not None or result.needs_review

    def test_spelled_partial_fragment_is_quarantined(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("zero six 66")
        assert result.value is None
        assert result.needs_review is True
        assert result.confidence == 0.3
