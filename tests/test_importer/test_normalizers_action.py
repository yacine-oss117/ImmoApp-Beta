"""Unit tests for action normalization."""

from __future__ import annotations

from core.importer.normalizers.action import ActionNormalizer


class TestActionNormalizerEdgeCases:
    """Edge case tests for action/transaction type normalization."""

    def test_action_achat_variations(self) -> None:
        """Test buy/purchase variations."""
        normalizer = ActionNormalizer()
        for term in ["Achat", "achat", "ACHAT", "acheter", "Acheter"]:
            result = normalizer.normalize(term)
            assert result.value == "buy"

    def test_action_vente_variations(self) -> None:
        """Test sell variations."""
        normalizer = ActionNormalizer()
        for term in ["Vente", "vente", "VENTE", "vendre", "Vendre", "à vendre"]:
            result = normalizer.normalize(term)
            assert result.value == "sell"

    def test_action_location_variations(self) -> None:
        """Test rent variations."""
        normalizer = ActionNormalizer()
        for term in ["Location", "location", "louer", "à louer", "Louer"]:
            result = normalizer.normalize(term)
            assert result.value == "rent"

    def test_action_arabic_terms(self) -> None:
        """Test Arabic action terms."""
        normalizer = ActionNormalizer()
        result_sell = normalizer.normalize("بيع")
        result_buy = normalizer.normalize("شراء")
        result_rent = normalizer.normalize("إيجار")
        assert result_sell.value == "sell" or result_sell.needs_review
        assert result_buy.value == "buy" or result_buy.needs_review
        assert result_rent.value == "rent" or result_rent.needs_review

    def test_action_combined_terms(self) -> None:
        """Test combined action terms."""
        normalizer = ActionNormalizer()
        result = normalizer.normalize("Vente ou Location")
        assert result.value in ("sell", "rent") or result.needs_review
