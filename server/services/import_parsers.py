"""
Parser selection helpers for import files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.importer.parsers import CsvParser, ExcelParser, OdsParser
from core.importer.parsers.csv_parser import CSV_EXTENSIONS
from server.services.import_constants import normalize_entity_type


def parser_for_filename(
    filename: str,
    *,
    sheet_name: str | None = None,
) -> tuple[Any, str] | None:
    ext = Path(filename).suffix.lower()
    if ext == ".xlsx":
        return ExcelParser(sheet_name=sheet_name), "excel"
    if ext in CSV_EXTENSIONS:
        return CsvParser(), "csv"
    if ext == ".ods":
        return OdsParser(sheet_name=sheet_name), "ods"
    return None


def parser_for_file_type(
    file_type: str,
    *,
    skip_rows: int = 0,
    sheet_name: str | None = None,
) -> Any:
    kind = (file_type or "").strip().lower()
    if kind == "csv":
        return CsvParser(skip_rows=skip_rows)
    if kind == "ods":
        return OdsParser(skip_rows=skip_rows, sheet_name=sheet_name)
    if kind == "excel":
        return ExcelParser(skip_rows=skip_rows, sheet_name=sheet_name)
    raise ValueError(f"Unsupported file type: {file_type}")


def normalize_import_entity_type(value: str | None) -> str:
    return normalize_entity_type(value)


__all__ = [
    "normalize_import_entity_type",
    "parser_for_file_type",
    "parser_for_filename",
]
