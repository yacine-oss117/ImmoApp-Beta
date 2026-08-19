from __future__ import annotations

import io
from decimal import Decimal

from server.services.import_runtime_artifacts import write_jsonl_entry


def test_write_jsonl_entry_accepts_decimal_payloads() -> None:
    handle = io.StringIO()

    write_jsonl_entry(handle, {"budget": Decimal("42.25"), "beds_min": Decimal("3")})

    assert handle.getvalue() == '{"budget":42.25,"beds_min":3}\n'
