"""
CSV file parser with auto-detection.

Supports CSV, TSV, and custom delimiters with encoding detection.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from itertools import chain
from pathlib import Path
from typing import TextIO

from core.importer.parsers.base import ParsedFile
from core.importer.security import (
    ensure_import_row_limit,
    import_security_limits,
    normalize_header_cells,
    normalize_row_cells,
)

logger = logging.getLogger(__name__)

# Supported file extensions
CSV_EXTENSIONS = {".csv", ".tsv", ".txt"}

# Common delimiters to try
COMMON_DELIMITERS = [",", ";", "\t", "|"]


class CsvParser:
    """Parser for CSV/TSV files.

    Attributes:
        delimiter: Specific delimiter (None = auto-detect).
        encoding: Specific encoding (None = auto-detect).
        skip_rows: Number of rows to skip before header.
        max_rows: Maximum rows to read (None = all).
    """

    def __init__(
        self,
        delimiter: str | None = None,
        encoding: str | None = None,
        skip_rows: int = 0,
        max_rows: int | None = None,
    ) -> None:
        """Initialize CSV parser.

        Args:
            delimiter: Delimiter character (None = auto-detect).
            encoding: File encoding (None = auto-detect).
            skip_rows: Number of rows to skip before reading.
            max_rows: Maximum number of data rows to read.
        """
        self.delimiter = delimiter
        self.encoding = encoding
        self.skip_rows = skip_rows
        self.max_rows = max_rows

    def can_parse(self, path: Path) -> bool:
        """Check if this parser can handle the file.

        Args:
            path: Path to check.

        Returns:
            True if file has CSV/TSV extension.
        """
        return path.suffix.lower() in CSV_EXTENSIONS

    def parse(self, path: Path) -> ParsedFile:
        """Parse a CSV file and return headers and first 100 rows for preview."""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        limits = import_security_limits()
        encoding = self.encoding or self._detect_encoding(path)
        preview_rows: list[dict[str, str]] = []
        headers: list[str] = []
        row_count = 0
        preview_limit = min(100, self.max_rows) if self.max_rows is not None else 100
        with path.open("r", encoding=encoding, errors="replace") as f:
            sample_lines = self._read_sample_lines(f)
            delimiter = self.delimiter or self._detect_delimiter("".join(sample_lines))
            logger.debug("CsvParser detected delimiter: %r", delimiter)
            previous_limit = csv.field_size_limit()
            csv.field_size_limit(limits.max_cell_chars)
            try:
                reader = csv.reader(chain(sample_lines, f), delimiter=delimiter)
                for _ in range(self.skip_rows):
                    next(reader, None)
                raw_headers = next(reader, [])
                headers = normalize_header_cells([str(h or "") for h in raw_headers])
                logger.debug("CsvParser detected headers: %s", headers)

                for row_values in reader:
                    normalized_values = normalize_row_cells(
                        [str(v or "") for v in row_values],
                        expected_cols=len(headers),
                    )
                    if not any(normalized_values):
                        continue

                    row_count += 1
                    ensure_import_row_limit(row_count)

                    if len(preview_rows) < preview_limit:
                        preview_rows.append(
                            {headers[index]: value for index, value in enumerate(normalized_values)}
                        )
            finally:
                csv.field_size_limit(previous_limit)

        warnings = []
        if self.max_rows and row_count > self.max_rows:
            warnings.append(f"max_rows limit of {self.max_rows} reached")

        parsed_file = ParsedFile(
            headers=[h.strip() for h in headers],
            rows=preview_rows,
            source_type="csv",
            source_path=path,
            encoding=encoding,
            row_count=row_count,
            warnings=warnings,
        )
        logger.debug("CsvParser returning ParsedFile row_count=%s", parsed_file.row_count)
        return parsed_file

    def iter_dicts(self, path: Path) -> Iterator[dict[str, str]]:
        """Yield row dictionaries one by one."""
        encoding = self.encoding or self._detect_encoding(path)

        with path.open("r", encoding=encoding, errors="replace") as f:
            sample_lines = self._read_sample_lines(f)
            delimiter = self.delimiter or self._detect_delimiter("".join(sample_lines))
            previous_limit = csv.field_size_limit()
            csv.field_size_limit(import_security_limits().max_cell_chars)
            try:
                reader = csv.reader(chain(sample_lines, f), delimiter=delimiter)
                for _ in range(self.skip_rows):
                    next(reader, None)
                headers_row = next(reader, None)
                if not headers_row:
                    return

                headers = normalize_header_cells([str(h or "") for h in headers_row])

                rows_yielded = 0
                max_rows = min(
                    self.max_rows or import_security_limits().max_rows,
                    import_security_limits().max_rows,
                )
                for row_values in reader:
                    normalized_values = normalize_row_cells(
                        [str(v or "") for v in row_values],
                        expected_cols=len(headers),
                    )
                    # Skip completely empty rows
                    if not any(normalized_values):
                        continue

                    row_dict: dict[str, str] = {}
                    for i, value in enumerate(normalized_values):
                        header = headers[i]
                        row_dict[header] = value
                    yield row_dict

                    rows_yielded += 1
                    ensure_import_row_limit(rows_yielded)
                    if rows_yielded >= max_rows:
                        return
            finally:
                csv.field_size_limit(previous_limit)

    def _read_sample_lines(self, handle: TextIO, sample_size: int = 20) -> list[str]:
        sample_lines: list[str] = []
        for _ in range(sample_size):
            line = handle.readline()
            if not line:
                break
            sample_lines.append(str(line))
        return sample_lines

    def _detect_encoding(self, path: Path) -> str:
        """Detect file encoding.

        Args:
            path: Path to file.

        Returns:
            Detected encoding name.
        """
        # Try chardet if available
        try:
            import chardet

            with path.open("rb") as f:
                raw = f.read(10000)  # Read first 10KB
            result = chardet.detect(raw)
            if result and result.get("encoding"):
                detected: str = str(result["encoding"])
                # Normalize common encodings
                if detected.lower() in ("ascii", "iso-8859-1", "windows-1252"):
                    return "utf-8"  # Default to UTF-8 for ASCII-compatible
                return detected
        except ImportError:
            pass

        # Fallback: try UTF-8, then Windows-1252
        try:
            with path.open("r", encoding="utf-8") as f:
                f.read(1000)
            return "utf-8"
        except UnicodeDecodeError:
            pass

        return "windows-1252"  # Common for Excel-exported CSVs

    def _detect_delimiter(self, sample: str) -> str:
        """Detect the delimiter used in CSV content.

        Args:
            sample: Sample of file content.

        Returns:
            Detected delimiter character.
        """
        if not sample:
            return ","

        # Count occurrences of each delimiter in first few lines
        lines = sample.splitlines()[:5]
        if not lines:
            return ","

        best_delimiter = ","
        best_score: float = float("-inf")

        for delimiter in COMMON_DELIMITERS:
            # Count delimiter occurrences per line
            counts = [line.count(delimiter) for line in lines]
            quoted_counts = [self._count_delimiter_inside_quotes(line, delimiter) for line in lines]

            # Good delimiter: appears consistently across lines
            if counts and min(counts) > 0:
                # Prefer candidates that split consistently across lines and do not
                # primarily appear inside quoted field content.
                consistency = 2.0 if len(set(counts)) == 1 else 1.0
                frequency = sum(counts) / len(counts)
                quoted_penalty = (sum(quoted_counts) / len(quoted_counts)) * 5.0
                score = (consistency * 10.0) + frequency - quoted_penalty

                if score > best_score:
                    best_score = score
                    best_delimiter = delimiter

        return best_delimiter

    def _count_delimiter_inside_quotes(self, line: str, delimiter: str) -> int:
        count = 0
        in_quotes = False
        index = 0
        while index < len(line):
            char = line[index]
            if char == '"':
                if in_quotes and index + 1 < len(line) and line[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = not in_quotes
            elif char == delimiter and in_quotes:
                count += 1
            index += 1
        return count
