"""Tests for ActionNormalizer."""

from __future__ import annotations

import pytest

from core.importer.normalizers.action import ActionNormalizer


@pytest.fixture
def normalizer() -> ActionNormalizer:
    return ActionNormalizer()


@pytest.fixture
def client_normalizer() -> ActionNormalizer:
    return ActionNormalizer(entity_type="client")


@pytest.fixture
def listing_normalizer() -> ActionNormalizer:
    return ActionNormalizer(entity_type="listing")


class TestActionNormalizer:
    """Test action normalization (buy/sell/rent)."""

    def test_vente(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("Vente")
        assert result.value is not None
        assert result.confidence >= 0.9

    def test_achat(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("Achat")
        assert result.value is not None
        assert result.confidence >= 0.9

    def test_location_rent(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("Location")
        assert result.value is not None
        assert result.confidence >= 0.9

    def test_sell_english(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("Sell")
        assert result.value is not None

    def test_buy_english(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("Buy")
        assert result.value is not None

    def test_rent_english(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("Rent")
        assert result.value is not None

    def test_arabic_sell(self, normalizer: ActionNormalizer) -> None:
        """للبيع should be recognized as sell."""
        result = normalizer.normalize("للبيع")
        assert result.value is not None

    def test_arabic_rent(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("للكراء")
        assert result.value is not None

    def test_typo_achter(self, normalizer: ActionNormalizer) -> None:
        """Common French typo of 'acheter'."""
        result = normalizer.normalize("achter")
        assert result.value is not None or result.needs_review

    def test_case_insensitive(self, normalizer: ActionNormalizer) -> None:
        r1 = normalizer.normalize("VENTE")
        r2 = normalizer.normalize("vente")
        assert r1.value == r2.value

    def test_empty(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("")
        assert result.value is None or result.value == ""

    def test_unknown_action(self, normalizer: ActionNormalizer) -> None:
        result = normalizer.normalize("XYZXYZ_UNKNOWN")
        assert result.needs_review or result.confidence < 0.5

    def test_entity_type_client_buy(self, client_normalizer: ActionNormalizer) -> None:
        """Client entity should accept 'buy'."""
        result = client_normalizer.normalize("Achat")
        assert result.value is not None

    def test_entity_type_listing_sell(self, listing_normalizer: ActionNormalizer) -> None:
        """Listing entity should accept 'sell'."""
        result = listing_normalizer.normalize("Vente")
        assert result.value is not None
