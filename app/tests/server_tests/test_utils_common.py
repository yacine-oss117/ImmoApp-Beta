"""
Coverage for common formatting and validation helpers.
"""

from __future__ import annotations

import pytest

from app.utils.common import (
    ensure_min_le_max,
    ensure_non_negative,
    fmt_int_group,
    fmt_money_range,
    fmt_money_short,
    norm_text,
    phone_digits,
    remove_diacritics,
    split_location_tokens,
    split_locs,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("resume", "resume"),
        ("résumé", "resume"),
        ("São Paulo", "Sao Paulo"),
        ("Çalışma", "Calisma"),
        ("éèà", "eea"),
        ("", ""),
    ],
)
def test_remove_diacritics(raw: str, expected: str) -> None:
    assert remove_diacritics(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Hello ", "hello"),
        ("Résumé", "resume"),
        ("Çalışma", "calisma"),
        ("", ""),
        (None, ""),
    ],
)
def test_norm_text(raw: str | None, expected: str) -> None:
    assert norm_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A;B", ["A", "B"]),
        ("A|B", ["A", "B"]),
        ("A\nB", ["A", "B"]),
        ("A,B", ["A,B"]),
        ("", []),
        ("  A  ;  B ", ["A", "B"]),
        ("A||B", ["A", "B"]),
    ],
)
def test_split_location_tokens(raw: str, expected: list[str]) -> None:
    assert split_location_tokens(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("École; Bab", ["ecole", "bab"]),
        ("Bab Ezzouar", ["bab ezzouar"]),
        ("A|B", ["a", "b"]),
        ("", []),
        ("  Résumé  ", ["resume"]),
    ],
)
def test_split_locs(raw: str, expected: list[str]) -> None:
    assert split_locs(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+213 (0)5 55-12-34-56", "2130555123456"),
        ("0555 12 34 56", "0555123456"),
        ("12-34", "1234"),
        ("", ""),
        (None, ""),
        ("abc", ""),
    ],
)
def test_phone_digits(raw: str | None, expected: str) -> None:
    assert phone_digits(raw) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1234, "1 234"),
        (1000000, "1 000 000"),
        ("9876", "9 876"),
        (0, "0"),
        ("bad", ""),
        (None, ""),
    ],
)
def test_fmt_int_group(value: object, expected: str) -> None:
    assert fmt_int_group(value) == expected


@pytest.mark.parametrize(
    ("value", "currency", "expected"),
    [
        (999, "", "999"),
        (1000, "", "1k"),
        (1500, "", "1.5k"),
        (1234, "", "1.234k"),
        (1_000_000, "", "1M"),
        (1_250_000, "", "1.25M"),
        (2_000_000_000, "", "2B"),
        (-1500, "", "-1.5k"),
        (1000, "DZD", "1k DZD"),
        (0, "", "0"),
        ("2,500", "", "2.5k"),
        (2_500_000_000, "", "2.5B"),
        (1_000_000, "USD", "1M USD"),
    ],
)
def test_fmt_money_short(value: object, currency: str, expected: str) -> None:
    assert fmt_money_short(value, currency) == expected


@pytest.mark.parametrize(
    ("min_value", "max_value", "currency", "expected"),
    [
        (1000, 2000, "", "1k - 2k"),
        (1500, 2500, "", "1.5k - 2.5k"),
        (500, 1500, "", "500 - 1.5k"),
        (None, 1500, "", ""),
        (1000, None, "", ""),
        (1000, 2000, "DZD", "1k - 2k DZD"),
    ],
)
def test_fmt_money_range(
    min_value: object, max_value: object, currency: str, expected: str
) -> None:
    assert fmt_money_range(min_value, max_value, currency) == expected


@pytest.mark.parametrize(
    ("value", "should_raise"),
    [
        (5, False),
        ("10", False),
        ("abc", False),
        (None, False),
        (-1, True),
        ("-2", True),
    ],
)
def test_ensure_non_negative(value: object, should_raise: bool) -> None:
    if should_raise:
        with pytest.raises(ValueError):
            ensure_non_negative(value, "field")
    else:
        assert ensure_non_negative(value, "field") == value


@pytest.mark.parametrize(
    ("min_value", "max_value", "zero_is_unset", "should_raise"),
    [
        (1, 2, False, False),
        (2, 1, False, True),
        ("5", "10", False, False),
        ("10", "5", False, True),
        (0, 0, True, False),
        (1, 0, True, False),
        (None, 5, False, False),
        (5, None, False, False),
    ],
)
def test_ensure_min_le_max(
    min_value: object, max_value: object, zero_is_unset: bool, should_raise: bool
) -> None:
    if should_raise:
        with pytest.raises(ValueError):
            ensure_min_le_max(min_value, max_value, "min", "max", zero_is_unset)
    else:
        ensure_min_le_max(min_value, max_value, "min", "max", zero_is_unset)
