"""Shared helpers for import API views."""

from __future__ import annotations

from typing import Any

from server.services.import_parsers import parser_for_filename


def get_parser_for_file(
    filename: str,
    *,
    sheet_name: str | None = None,
) -> tuple[Any, str] | None:
    """Get appropriate parser and file type based on file extension."""
    return parser_for_filename(filename, sheet_name=sheet_name)
