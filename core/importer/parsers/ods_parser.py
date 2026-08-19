"""
ODS (OpenDocument Spreadsheet) parser.

Supports .ods files from LibreOffice, OpenOffice, and Google Sheets exports.
Uses a streaming XML parser for better performance on large files.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile

from core.importer.parsers.base import ParsedFile
from core.importer.security import (
    ensure_import_row_limit,
    import_security_limits,
    normalize_header_cells,
    normalize_row_cells,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Supported file extensions
ODS_EXTENSIONS = {".ods"}

_TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_SPREADSHEET_TAG = f"{{{_OFFICE_NS}}}spreadsheet"
_TABLE_TAG = f"{{{_TABLE_NS}}}table"
_ROW_TAG = f"{{{_TABLE_NS}}}table-row"
_CELL_TAG = f"{{{_TABLE_NS}}}table-cell"
_COVERED_CELL_TAG = f"{{{_TABLE_NS}}}covered-table-cell"
_ATTR_TABLE_NAME = f"{{{_TABLE_NS}}}name"
_ATTR_COL_REPEAT = f"{{{_TABLE_NS}}}number-columns-repeated"
_ATTR_ROW_REPEAT = f"{{{_TABLE_NS}}}number-rows-repeated"


class OdsParser:
    """Parser for ODS files (OpenDocument Spreadsheet)."""

    def __init__(
        self,
        sheet_name: str | None = None,
        skip_rows: int = 0,
        max_rows: int | None = None,
    ) -> None:
        self.sheet_name = sheet_name
        self.skip_rows = skip_rows
        self.max_rows = max_rows

    def can_parse(self, path: Path) -> bool:
        """Check if this parser can handle the file."""
        return path.suffix.lower() in ODS_EXTENSIONS

    def parse(self, path: Path) -> ParsedFile:
        """Parse an ODS file and return headers and first 100 rows for preview."""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        self._validate_archive(path)
        self._validate_sheet_count(path)
        rows_iter = self._iter_sheet_rows(path)

        # Skip pre-header rows if requested.
        for _ in range(max(0, self.skip_rows)):
            if next(rows_iter, None) is None:
                return ParsedFile(headers=[], rows=[], source_type="ods", source_path=path)

        header_row: list[str] | None = None
        for candidate in rows_iter:
            if self._has_non_empty_values(candidate):
                header_row = candidate
                break
        if not header_row:
            return ParsedFile(headers=[], rows=[], source_type="ods", source_path=path)

        headers = normalize_header_cells(header_row)
        expected_cols = len(headers)

        # Keep preview small for UI responsiveness.
        preview_rows: list[dict[str, str]] = []
        preview_limit = 100
        row_count = 0

        for row_values in rows_iter:
            row_count += 1
            normalized_values = normalize_row_cells(row_values, expected_cols=expected_cols)
            if not any(normalized_values):
                continue

            if len(preview_rows) < preview_limit:
                preview_rows.append(
                    {headers[i]: normalized_values[i] for i in range(expected_cols)}
                )

            if self.max_rows is not None and row_count >= self.max_rows:
                break
            ensure_import_row_limit(row_count)

        return ParsedFile(
            headers=headers,
            rows=preview_rows,
            source_type="ods",
            source_path=path,
            sheet_name=self.sheet_name or "Sheet1",
            row_count=max(0, row_count),
        )

    def iter_dicts(self, path: Path) -> Iterator[dict[str, str]]:
        """Yield row dictionaries one by one."""
        self._validate_archive(path)
        self._validate_sheet_count(path)
        rows_iter = self._iter_sheet_rows(path)

        for _ in range(max(0, self.skip_rows)):
            if next(rows_iter, None) is None:
                return

        header_row: list[str] | None = None
        for candidate in rows_iter:
            if self._has_non_empty_values(candidate):
                header_row = candidate
                break
        if not header_row:
            return

        headers = normalize_header_cells(header_row)
        expected_cols = len(headers)

        yielded = 0
        for row_values in rows_iter:
            normalized_values = normalize_row_cells(row_values, expected_cols=expected_cols)
            if not any(normalized_values):
                continue

            yield {headers[i]: normalized_values[i] for i in range(expected_cols)}
            yielded += 1
            ensure_import_row_limit(yielded)
            if self.max_rows is not None and yielded >= self.max_rows:
                return

    def get_sheet_names(self, path: Path) -> list[str]:
        """Get list of sheet names in document."""
        self._validate_archive(path)
        names: list[str] = []
        with ZipFile(path) as archive:
            with archive.open("content.xml") as content:
                for _event, elem in ET.iterparse(content, events=("start",)):
                    if elem.tag == _TABLE_TAG:
                        names.append(elem.attrib.get(_ATTR_TABLE_NAME) or f"Sheet{len(names) + 1}")
                    elem.clear()
        return names

    def _validate_sheet_count(self, path: Path) -> None:
        names = self.get_sheet_names(path)
        if len(names) > import_security_limits().max_sheets:
            raise ValueError(
                "Spreadsheet exceeds the maximum supported sheet count "
                f"({import_security_limits().max_sheets})."
            )

    def _iter_sheet_rows(self, path: Path) -> Iterator[list[str]]:
        """Stream rows from selected sheet without loading full XML DOM."""
        with ZipFile(path) as archive:
            try:
                content = archive.open("content.xml")
            except KeyError as exc:
                raise ValueError("Invalid ODS file: content.xml is missing") from exc

            with content:
                target_sheet = self.sheet_name
                in_target_table = False
                table_depth = 0
                spreadsheet_depth = 0

                for event, elem in ET.iterparse(content, events=("start", "end")):
                    tag = elem.tag

                    if event == "start":
                        if tag == _SPREADSHEET_TAG:
                            spreadsheet_depth += 1
                            continue
                        if tag == _TABLE_TAG:
                            if spreadsheet_depth <= 0:
                                continue
                            if not in_target_table:
                                table_name = elem.attrib.get(_ATTR_TABLE_NAME)
                                if target_sheet is None or table_name == target_sheet:
                                    in_target_table = True
                                    table_depth = 1
                            elif in_target_table:
                                table_depth += 1
                        continue

                    # end events below
                    if in_target_table and tag == _ROW_TAG:
                        row_values = self._extract_row_values(elem)
                        row_repeat = self._parse_repeat(elem.attrib.get(_ATTR_ROW_REPEAT))
                        for _ in range(row_repeat):
                            yield row_values.copy()
                        elem.clear()
                        continue

                    if in_target_table and tag == _TABLE_TAG:
                        table_depth -= 1
                        if table_depth <= 0:
                            break
                        elem.clear()
                        continue

                    if tag == _SPREADSHEET_TAG:
                        spreadsheet_depth = max(0, spreadsheet_depth - 1)
                        elem.clear()
                        continue

    def _extract_row_values(self, row_elem: ET.Element) -> list[str]:
        limits = import_security_limits()
        values: list[str] = []
        for cell in row_elem:
            if cell.tag not in (_CELL_TAG, _COVERED_CELL_TAG):
                continue
            text = "".join(cell.itertext()).strip()
            repeat = self._parse_repeat(cell.attrib.get(_ATTR_COL_REPEAT))
            if len(text) > limits.max_cell_chars:
                raise ValueError(
                    f"Import cell exceeds the maximum supported length ({limits.max_cell_chars})."
                )
            projected = len(values) + repeat
            if projected > limits.max_columns:
                raise ValueError(
                    f"Import file exceeds the maximum supported column count ({limits.max_columns})."
                )
            values.extend([text] * repeat)
        return values

    @staticmethod
    def _parse_repeat(raw: str | None) -> int:
        if not raw:
            return 1
        try:
            value = int(raw)
        except ValueError:
            return 1
        return max(1, value)

    @staticmethod
    def _has_non_empty_values(values: list[str]) -> bool:
        return any(v.strip() for v in values)

    def _validate_archive(self, path: Path) -> None:
        limits = import_security_limits()
        compression_ratio_guard_floor = 1024 * 1024
        with ZipFile(path) as archive:
            infos = archive.infolist()
            if not infos:
                raise ValueError("Import archive is invalid or empty.")
            if len(infos) > limits.max_archive_entries:
                raise ValueError(
                    f"Import archive exceeds the maximum entry count ({limits.max_archive_entries})."
                )
            total_uncompressed = sum(max(0, int(info.file_size or 0)) for info in infos)
            if total_uncompressed > limits.max_archive_uncompressed_bytes:
                raise ValueError("Import archive expands beyond the maximum supported size.")
            total_compressed = sum(max(0, int(info.compress_size or 0)) for info in infos)
            if total_uncompressed >= compression_ratio_guard_floor and total_uncompressed / max(
                1, total_compressed
            ) > float(limits.max_archive_compression_ratio):
                raise ValueError("Import archive compression ratio is suspiciously high.")
            if (
                len([info for info in infos if info.filename.endswith("/")])
                > limits.max_archive_entries
            ):
                raise ValueError("Import archive structure is invalid.")
            names = {info.filename for info in infos}
            if "content.xml" not in names or "mimetype" not in names:
                raise ValueError("Import archive is missing required ODS entries.")
