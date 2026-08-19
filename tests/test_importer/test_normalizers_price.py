"""Unit tests for price normalization."""

from __future__ import annotations

import pytest

from core.importer.normalizers.base import RowContext
from core.importer.normalizers.price import PriceNormalizer


class TestPriceNormalizer:
    """Tests for PriceNormalizer."""

    @pytest.fixture
    def normalizer(self) -> PriceNormalizer:
        """Create price normalizer instance."""
        return PriceNormalizer()

    def test_empty_value(self, normalizer: PriceNormalizer) -> None:
        """Test empty value returns None."""
        result = normalizer.normalize("")
        assert result.value is None
        assert result.confidence == 1.0

    def test_m_suffix_is_ambiguous_without_context(self, normalizer: PriceNormalizer) -> None:
        """Bare M shorthand should wait for a dialect hint."""
        result = normalizer.normalize("2.5M")
        assert result.value is None
        assert result.needs_review is True
        assert result.extracted_extras["price_ambiguity_reason_codes"] == [
            "ambiguous_million_token"
        ]

    def test_m_suffix_resolves_with_dzd_hint(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize(
            "3M",
            RowContext(
                metadata={"price_dialect_hint": "dzd_millions", "price_dialect_confidence": 0.9}
            ),
        )
        assert result.value == 3_000_000
        assert result.needs_review is False

    def test_m_suffix_resolves_with_centime_hint(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize(
            "2,5M",
            RowContext(
                metadata={
                    "price_dialect_hint": "centime_millions",
                    "price_dialect_confidence": 0.91,
                }
            ),
        )
        assert result.value == 25_000

    def test_m_suffix_resolves_with_explicit_dzd_header(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize(
            "1.5M",
            RowContext(metadata={"price_unit_hint": "dzd", "source_header": "Budget (DZD)"}),
        )
        assert result.value == 1_500_000
        assert result.needs_review is False

    def test_m_suffix_resolves_with_explicit_centime_header(
        self, normalizer: PriceNormalizer
    ) -> None:
        result = normalizer.normalize(
            "1.5M",
            RowContext(metadata={"price_unit_hint": "centime", "source_header": "Budget (CTS)"}),
        )
        assert result.value == 15_000
        assert result.needs_review is False

    def test_millions_text_is_ambiguous_without_anchor(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2.5 millions")
        assert result.value is None
        assert result.needs_review is True

    def test_million_singular_defaults_to_review(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("1 million")
        assert result.value is None
        assert result.needs_review is True

    def test_raw_number(self, normalizer: PriceNormalizer) -> None:
        """Test raw number."""
        result = normalizer.normalize("2500000")
        assert result.value == 2_500_000
        assert result.confidence == 1.0

    def test_number_with_spaces(self, normalizer: PriceNormalizer) -> None:
        """Test number with spaces (2 500 000)."""
        result = normalizer.normalize("2 500 000")
        assert result.value == 2_500_000
        assert result.confidence == 1.0

    def test_european_format(self, normalizer: PriceNormalizer) -> None:
        """Test European format with dots (2.500.000)."""
        result = normalizer.normalize("2.500.000")
        assert result.value == 2_500_000
        assert result.confidence == 1.0

    def test_us_format(self, normalizer: PriceNormalizer) -> None:
        """Test US format with commas (2,500,000)."""
        result = normalizer.normalize("2,500,000")
        assert result.value == 2_500_000
        assert result.confidence == 1.0

    def test_with_currency_da(self, normalizer: PriceNormalizer) -> None:
        """Test with DA currency."""
        result = normalizer.normalize("2500000 DA")
        assert result.value == 2_500_000

    def test_with_currency_arabic(self, normalizer: PriceNormalizer) -> None:
        """Test with Arabic currency symbol."""
        result = normalizer.normalize("2500000 دج")
        assert result.value == 2_500_000

    def test_format_display(self, normalizer: PriceNormalizer) -> None:
        """Test display formatting."""
        formatted = normalizer.format_display(2_500_000)
        assert formatted == "2 500 000 DA"

    def test_format_short(self, normalizer: PriceNormalizer) -> None:
        """Test short format."""
        assert normalizer.format_short(2_500_000) == "2.5M"
        assert normalizer.format_short(3_000_000) == "3M"
        assert normalizer.format_short(150_000) == "150K"

    def test_unparseable(self, normalizer: PriceNormalizer) -> None:
        """Test unparseable value."""
        result = normalizer.normalize("à discuter")
        assert result.value is None
        assert result.confidence == 0.0
        assert result.needs_review is True

    def test_milliard_defaults_to_colloquial_centime_mode(
        self, normalizer: PriceNormalizer
    ) -> None:
        result = normalizer.normalize("1.5 milliard")
        assert result.value == 15_000_000

    def test_milliard_compound_defaults_to_colloquial_centime_mode(
        self, normalizer: PriceNormalizer
    ) -> None:
        result = normalizer.normalize("1 milliard 500")
        assert result.value == 15_000_000

    def test_explicit_dzd_overrides_colloquial_milliard(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("1 milliard 500 DZD")
        assert result.value == 1_500_000_000

    def test_monthly_millions_default_to_colloquial_centime_rent(
        self, normalizer: PriceNormalizer
    ) -> None:
        result = normalizer.normalize("5 millions/mois")
        assert result.value == 50_000
        assert result.extracted_extras["cadence"] == "monthly"

    def test_monthly_millions_dzd_remain_dzd(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("5 millions/mois DZD")
        assert result.value == 5_000_000
        assert result.extracted_extras["cadence"] == "monthly"

    def test_bare_decimal_never_digit_stitches(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("1.5")
        assert result.value is None
        assert result.needs_review is True
        assert result.extracted_extras["price_ambiguity_reason_codes"] == [
            "ambiguous_decimal_no_scale"
        ]

    def test_centimes_mode(self) -> None:
        """Test output in centimes mode."""
        normalizer = PriceNormalizer(output_in_centimes=True)
        result = normalizer.normalize(
            "2.5M DZD",
            RowContext(
                metadata={"price_dialect_hint": "dzd_millions", "price_dialect_confidence": 0.9}
            ),
        )
        assert result.value == 250_000_000  # 2.5M DZD * 100


class TestPriceNormalizerEdgeCases:
    """Edge case tests for price normalization."""

    @pytest.fixture
    def normalizer(self) -> PriceNormalizer:
        return PriceNormalizer()

    def test_price_with_arabic_numerals(self, normalizer: PriceNormalizer) -> None:
        """Test price with Arabic-Indic numerals."""
        result = normalizer.normalize("١٥٠٠٠٠٠٠")
        assert result.value == 15000000
        assert result.needs_review is False

    def test_price_negative(self, normalizer: PriceNormalizer) -> None:
        """Test negative price."""
        result = normalizer.normalize("-5000000")
        assert result.value is None
        assert result.needs_review is True
        assert result.extracted_extras["negative_price_detected"] is True

    def test_negative_ambiguous_million_keeps_negative_metadata(
        self, normalizer: PriceNormalizer
    ) -> None:
        result = normalizer.normalize("-1.5M")
        assert result.value is None
        assert result.needs_review is True
        assert result.extracted_extras["negative_price_detected"] is True

    def test_price_zero(self, normalizer: PriceNormalizer) -> None:
        """Test zero price."""
        result = normalizer.normalize("0")
        assert result.value == 0 or result.needs_review

    def test_price_very_large(self, normalizer: PriceNormalizer) -> None:
        """Test extremely large price (billion+)."""
        result = normalizer.normalize("999999999999")
        assert result.value == 999999999999 or result.needs_review

    def test_price_with_currency_symbol(self, normalizer: PriceNormalizer) -> None:
        """Test price with DA currency."""
        result = normalizer.normalize("15M DA")
        assert result.value == 15000000

    def test_price_with_dz_suffix(self, normalizer: PriceNormalizer) -> None:
        """Test price with DZD suffix."""
        result = normalizer.normalize("15000000 DZD")
        assert result.value == 15000000
        assert result.needs_review is False

    def test_price_french_notation(self, normalizer: PriceNormalizer) -> None:
        """Test French number notation (space as thousands separator)."""
        result = normalizer.normalize("15 000 000")
        assert result.value == 15000000

    def test_price_with_k_suffix(self, normalizer: PriceNormalizer) -> None:
        """Test price with K suffix (thousands)."""
        result = normalizer.normalize("15000K")
        assert result.value == 15000000
        assert result.needs_review is False

    def test_price_decimal_millions(self, normalizer: PriceNormalizer) -> None:
        """Test decimal with M suffix."""
        result = normalizer.normalize("1.5M")
        assert result.value is None
        assert result.needs_review is True

    def test_price_with_html_entities(self, normalizer: PriceNormalizer) -> None:
        """Test price copied from webpage with artifacts."""
        result = normalizer.normalize("15&nbsp;000&nbsp;000")
        assert result.value == 15000000
        assert result.needs_review is False

    def test_explicit_centime_scalar_converts_to_dzd(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("150 centimes")
        assert result.value == 1.5
