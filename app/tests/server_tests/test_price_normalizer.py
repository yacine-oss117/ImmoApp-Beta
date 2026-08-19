"""Tests for PriceNormalizer."""

from __future__ import annotations

import pytest

from core.importer.normalizers.base import RowContext
from core.importer.normalizers.price import PriceNormalizer


@pytest.fixture
def normalizer() -> PriceNormalizer:
    return PriceNormalizer()


class TestPriceNormalizer:
    """Test Algerian price normalization."""

    def test_plain_integer(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2500000")
        assert result.value == 2_500_000
        assert result.confidence >= 0.9

    def test_m_suffix_upper(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2.5M")
        assert result.value is None
        assert result.needs_review is True

    def test_m_suffix_lower(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2.5m")
        assert result.value is None
        assert result.needs_review is True

    def test_k_suffix(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("15K")
        assert result.value == 15_000

    def test_millions_text_fr(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2.5 millions")
        assert result.value is None
        assert result.needs_review is True

    def test_million_text_fr(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2 million")
        assert result.value is None
        assert result.needs_review is True

    def test_european_dot_separator(self, normalizer: PriceNormalizer) -> None:
        """European format: dots as thousand separators."""
        result = normalizer.normalize("2.500.000")
        assert result.value == 2_500_000

    def test_us_comma_separator(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2,500,000")
        assert result.value == 2_500_000

    def test_spaced_number(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2 500 000")
        assert result.value == 2_500_000

    def test_currency_da_stripped(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2500000 DA")
        assert result.value == 2_500_000

    def test_currency_dzd_stripped(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("2500000 DZD")
        assert result.value == 2_500_000

    def test_milliard(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("1.5 milliard")
        assert result.value == 15_000_000
        assert result.confidence >= 0.95

    def test_milliard_compound(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("1 milliard 500")
        assert result.value == 15_000_000
        assert result.confidence >= 0.9

    def test_explicit_dzd_milliard_compound(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("1 milliard 500 DZD")
        assert result.value == 1_500_000_000

    def test_monthly_million_price_keeps_cadence_metadata(
        self, normalizer: PriceNormalizer
    ) -> None:
        result = normalizer.normalize("5 millions/mois")
        assert result.value == 50_000
        assert result.extracted_extras["cadence"] == "monthly"

    def test_ambiguous_unknown_suffix_stays_review(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("15000 u")
        assert result.value is None
        assert result.needs_review is True

    def test_zero(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("0")
        assert result.value == 0

    def test_empty(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("")
        assert result.value is None or result.value == 0

    def test_unparseable(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("abc")
        assert result.needs_review or result.confidence < 0.5

    def test_negative_value(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize("-500000")
        # Negative prices should be flagged
        assert result.needs_review or result.value is None or result.value < 0
        assert result.extracted_extras.get("negative_price_detected") is True

    def test_decimal_price(self, normalizer: PriceNormalizer) -> None:
        """Price with centimes."""
        result = normalizer.normalize("2500000.50")
        assert result.value is not None
        assert result.confidence >= 0.5

    def test_bare_decimal_price_is_review_not_digit_stitch(
        self, normalizer: PriceNormalizer
    ) -> None:
        result = normalizer.normalize("1.5")
        assert result.value is None
        assert result.needs_review is True

    def test_m_with_space_uses_column_dialect_hint(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize(
            "2.5 M",
            RowContext(
                metadata={
                    "price_dialect_hint": "dzd_millions",
                    "price_dialect_confidence": 0.91,
                }
            ),
        )
        assert result.value == 2_500_000

    def test_m_with_space_uses_centime_hint(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize(
            "1.5 m",
            RowContext(
                metadata={
                    "price_dialect_hint": "centime_millions",
                    "price_dialect_confidence": 0.91,
                }
            ),
        )
        assert result.value == 15_000

    def test_m_with_explicit_dzd_header_prefers_dzd(self, normalizer: PriceNormalizer) -> None:
        result = normalizer.normalize(
            "1.5 M",
            RowContext(
                metadata={"price_unit_hint": "dzd", "source_header": "Budget max/Prix (DZD)"}
            ),
        )
        assert result.value == 1_500_000
        assert result.needs_review is False

    def test_m_with_explicit_centime_header_prefers_centime(
        self, normalizer: PriceNormalizer
    ) -> None:
        result = normalizer.normalize(
            "1.5 M",
            RowContext(metadata={"price_unit_hint": "centime", "source_header": "Budget (CTS)"}),
        )
        assert result.value == 15_000
        assert result.needs_review is False
