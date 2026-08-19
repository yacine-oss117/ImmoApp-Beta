"""Unit tests for normalizer base types."""

from __future__ import annotations

from core.importer.normalizers.base import NormalizeResult, RowContext


class TestNormalizeResult:
    """Tests for NormalizeResult dataclass."""

    def test_is_high_confidence_default(self) -> None:
        """Test high confidence check with default threshold."""
        result = NormalizeResult(value="test", confidence=0.9, original="test")
        assert result.is_high_confidence() is True

        result = NormalizeResult(value="test", confidence=0.8, original="test")
        assert result.is_high_confidence() is False

    def test_is_high_confidence_custom_threshold(self) -> None:
        """Test high confidence check with custom threshold."""
        result = NormalizeResult(value="test", confidence=0.7, original="test")
        assert result.is_high_confidence(threshold=0.6) is True
        assert result.is_high_confidence(threshold=0.8) is False

    def test_is_empty(self) -> None:
        """Test empty value detection."""
        assert NormalizeResult(value=None, confidence=1.0, original="").is_empty() is True
        assert NormalizeResult(value="", confidence=1.0, original="").is_empty() is True
        assert NormalizeResult(value="test", confidence=1.0, original="test").is_empty() is False


class TestRowContext:
    """Tests for RowContext dataclass."""

    def test_default_values(self) -> None:
        """Test default values are None/empty."""
        ctx = RowContext()
        assert ctx.wilaya_hint is None
        assert ctx.action_hint is None
        assert ctx.type_hint is None
        assert ctx.row_data == {}
