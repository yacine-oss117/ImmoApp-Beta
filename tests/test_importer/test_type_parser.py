from __future__ import annotations

from core.importer.type_parser import TypeParser


def test_calculate_float_value_treats_comma_thousands_separator_as_integer() -> None:
    assert TypeParser.calculate_float_value("1,500") == 1500.0


def test_calculate_float_value_treats_comma_decimal_as_decimal() -> None:
    assert TypeParser.calculate_float_value("12,5") == 12.5


def test_calculate_float_value_handles_arabic_digits() -> None:
    assert TypeParser.calculate_float_value("١٢,٥") == 12.5
