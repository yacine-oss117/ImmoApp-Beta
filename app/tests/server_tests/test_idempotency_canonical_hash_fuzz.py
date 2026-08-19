from __future__ import annotations

import random
from typing import Any

from core.contracts.idempotency_canonical_json import canonical_body_hash, canonical_query_hash


def _random_scalar(rng: random.Random) -> Any:
    pick = rng.randint(0, 5)
    if pick == 0:
        return rng.randint(-10_000, 10_000)
    if pick == 1:
        # Keep finite floats only.
        return round(rng.uniform(-10_000.0, 10_000.0), 4)
    if pick == 2:
        return bool(rng.randint(0, 1))
    if pick == 3:
        return None
    if pick == 4:
        return f"v{rng.randint(0, 999)}"
    return ""


def _random_json(rng: random.Random, depth: int = 0) -> Any:
    if depth >= 3:
        return _random_scalar(rng)
    pick = rng.randint(0, 2)
    if pick == 0:
        out: dict[str, Any] = {}
        for _ in range(rng.randint(0, 4)):
            out[f"k{rng.randint(0, 12)}"] = _random_json(rng, depth + 1)
        return out
    if pick == 1:
        return [_random_json(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return _random_scalar(rng)


def _shuffle_dict_order(value: Any, rng: random.Random) -> Any:
    if isinstance(value, dict):
        items = list(value.items())
        rng.shuffle(items)
        return {k: _shuffle_dict_order(v, rng) for k, v in items}
    if isinstance(value, list):
        return [_shuffle_dict_order(v, rng) for v in value]
    return value


def test_canonical_body_hash_fuzz_is_stable_under_key_order_changes() -> None:
    rng = random.Random(20260226)
    for _ in range(120):
        payload = _random_json(rng)
        reordered = _shuffle_dict_order(payload, rng)
        assert canonical_body_hash(payload) == canonical_body_hash(reordered)


def test_canonical_query_hash_fuzz_is_stable_under_key_order_changes() -> None:
    rng = random.Random(20260226)
    for _ in range(120):
        query_dict: dict[str, object] = {}
        for _ in range(rng.randint(1, 6)):
            key = f"q{rng.randint(0, 10)}"
            if rng.randint(0, 1) == 0:
                query_dict[key] = _random_scalar(rng)
            else:
                query_dict[key] = [_random_scalar(rng) for _ in range(rng.randint(0, 4))]
        reordered = _shuffle_dict_order(query_dict, rng)
        assert canonical_query_hash(query_dict) == canonical_query_hash(reordered)
