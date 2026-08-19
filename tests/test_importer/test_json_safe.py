from __future__ import annotations

from decimal import Decimal

from server.services.json_safe import json_safe_value


def test_json_safe_value_converts_nested_decimals() -> None:
    payload = {
        "price": Decimal("12.5"),
        "count": Decimal("7"),
        "items": [{"budget": Decimal("99.75")}],
    }

    safe = json_safe_value(payload)

    assert safe == {"price": 12.5, "count": 7, "items": [{"budget": 99.75}]}
