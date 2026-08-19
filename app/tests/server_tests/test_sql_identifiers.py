"""
Tests for SQL identifier validation helpers.
"""

from __future__ import annotations

import pytest

from core.data.sql_identifiers import ensure_safe_identifier, validate_identifier


@pytest.mark.parametrize(
    "value",
    [
        "table",
        "Table_1",
        "_x",
        "a1",
        "A_B2",
        "column_name",
    ],
)
def test_validate_identifier_accepts_safe(value: str) -> None:
    assert validate_identifier(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "1abc",
        "bad-name",
        "has space",
        "semi;colon",
        "drop table",
        "select*",
        "weird!",
    ],
)
def test_validate_identifier_rejects_unsafe(value: str) -> None:
    with pytest.raises(ValueError):
        validate_identifier(value)


def test_validate_identifier_respects_allowed_set() -> None:
    allowed = {"clients", "listings"}
    assert validate_identifier("clients", allowed=allowed, kind="table") == "clients"
    with pytest.raises(ValueError):
        validate_identifier("offers", allowed=allowed, kind="table")


def test_ensure_safe_identifier_uses_kind_in_error() -> None:
    with pytest.raises(ValueError) as exc:
        ensure_safe_identifier("bad-name", kind="column")
    assert "column" in str(exc.value)
