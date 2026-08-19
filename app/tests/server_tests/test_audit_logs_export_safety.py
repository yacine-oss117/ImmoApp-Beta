from __future__ import annotations

from app.utils.csv_safety import csv_safe


def test_csv_safe_prefixes_formula_like_cells() -> None:
    assert csv_safe("=1+1") == "'=1+1"
    assert csv_safe("+SUM(A1:A2)") == "'+SUM(A1:A2)"
    assert csv_safe("-10+cmd") == "'-10+cmd"
    assert csv_safe("@cmd") == "'@cmd"
    assert csv_safe("  =hidden") == "'  =hidden"


def test_csv_safe_leaves_normal_cells_unchanged() -> None:
    assert csv_safe("hello") == "hello"
    assert csv_safe("  hello") == "  hello"
    assert csv_safe(42) == "42"
