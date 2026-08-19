from __future__ import annotations

from decimal import Decimal

from core.utils.row_casts import as_int


def test_as_int_accepts_decimal() -> None:
    assert as_int(Decimal("42")) == 42
