"""Unit tests for boolean normalization."""

from __future__ import annotations

from core.importer.normalizers.boolean import BooleanNormalizer


class TestBooleanNormalizerEdgeCases:
    """Edge case tests for boolean normalization."""

    def test_boolean_french_oui_non(self) -> None:
        """Test French yes/no."""
        normalizer = BooleanNormalizer()
        assert normalizer.normalize("oui").value is True
        assert normalizer.normalize("non").value is False
        assert normalizer.normalize("OUI").value is True
        assert normalizer.normalize("NON").value is False

    def test_boolean_arabic_yes_no(self) -> None:
        """Test Arabic yes/no."""
        normalizer = BooleanNormalizer()
        result_yes = normalizer.normalize("نعم")
        result_no = normalizer.normalize("لا")
        assert result_yes.value is True or result_yes.needs_review
        assert result_no.value is False or result_no.needs_review

    def test_boolean_checkbox_symbols(self) -> None:
        """Test checkbox-like symbols."""
        normalizer = BooleanNormalizer()
        assert normalizer.normalize("✓").value is True
        assert normalizer.normalize("✗").value is False or normalizer.normalize("✗").needs_review
        assert normalizer.normalize("☑").value is True or normalizer.normalize("☑").needs_review
        assert normalizer.normalize("☐").value is False or normalizer.normalize("☐").needs_review

    def test_boolean_empty_values(self) -> None:
        """Test empty/null interpretations."""
        normalizer = BooleanNormalizer()
        assert normalizer.normalize("").value is None
        assert normalizer.normalize("   ").value is None
        assert normalizer.normalize("-").value is None
        assert normalizer.normalize("N/A").value is None

    def test_x_requires_review_not_auto_true(self) -> None:
        normalizer = BooleanNormalizer()
        result = normalizer.normalize("x")
        assert result.value is None
        assert result.needs_review is True
