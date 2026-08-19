from __future__ import annotations

import math

import pytest

from core.contracts.idempotency_canonical_json import canonical_body_hash, canonical_json_dumps


def test_canonical_hash_is_stable_for_key_order() -> None:
    left = {"b": 2, "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": 2}
    assert canonical_body_hash(left) == canonical_body_hash(right)


def test_canonical_hash_preserves_numeric_intent_for_int_vs_float() -> None:
    assert canonical_json_dumps({"v": 1}) != canonical_json_dumps({"v": 1.0})
    assert canonical_body_hash({"v": 1}) != canonical_body_hash({"v": 1.0})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), math.nan])
def test_non_finite_float_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        canonical_json_dumps({"v": value})
