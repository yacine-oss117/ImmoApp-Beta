from __future__ import annotations

from hypothesis import given, strategies as st

from core.importer.normalizers.action import ActionNormalizer
from core.importer.normalizers.base import NormalizeResult
from core.importer.normalizers.boolean import BooleanNormalizer
from core.importer.normalizers.phone import PhoneNormalizer
from core.importer.normalizers.price import PriceNormalizer
from core.importer.normalizers.property_type import PropertyTypeNormalizer


@given(st.text(max_size=200))
def test_phone_normalizer_never_crashes(text: str) -> None:
    result = PhoneNormalizer().normalize(text)
    assert isinstance(result, NormalizeResult)
    assert 0.0 <= result.confidence <= 1.0
    if result.value is not None:
        assert isinstance(result.value, str)
        assert len(result.value) == 10
        assert result.value.isdigit()


@given(st.text(max_size=200))
def test_price_normalizer_never_crashes(text: str) -> None:
    result = PriceNormalizer().normalize(text)
    assert isinstance(result, NormalizeResult)
    assert 0.0 <= result.confidence <= 1.0
    if result.value is not None:
        assert isinstance(result.value, (int, float))
        assert result.value >= 0


@given(st.text(max_size=200))
def test_property_type_normalizer_never_crashes(text: str) -> None:
    result = PropertyTypeNormalizer().normalize(text)
    assert isinstance(result, NormalizeResult)
    assert 0.0 <= result.confidence <= 1.0


@given(st.text(max_size=200))
def test_boolean_normalizer_never_crashes(text: str) -> None:
    result = BooleanNormalizer().normalize(text)
    assert isinstance(result, NormalizeResult)
    assert 0.0 <= result.confidence <= 1.0


@given(st.text(max_size=200))
def test_action_normalizer_never_crashes(text: str) -> None:
    result = ActionNormalizer().normalize(text)
    assert isinstance(result, NormalizeResult)
    assert 0.0 <= result.confidence <= 1.0
