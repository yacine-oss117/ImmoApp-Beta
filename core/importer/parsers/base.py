"""
Base parser protocol and shared data structures.

All parsers return a ParsedFile dataclass with headers and rows.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ParsedFile:
    """Result of parsing a file.

    Attributes:
        headers: Column headers (may be empty if no header row detected).
        rows: List of row dictionaries mapping header → value.
        source_type: File type that was parsed (e.g., "excel", "csv").
        source_path: Original file path.
        encoding: Detected or used encoding.
        row_count: Total number of data rows (excluding header).
        sheet_name: For Excel files, the sheet that was parsed.
    """

    headers: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)
    source_type: str = ""
    source_path: Path | None = None
    encoding: str = "utf-8"
    row_count: int = 0
    sheet_name: str | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Set row_count if not provided."""
        if self.row_count == 0:
            self.row_count = len(self.rows)


class Parser(Protocol):
    """Protocol for file parsers.

    All parsers must implement the parse method.
    """

    def parse(self, path: Path) -> ParsedFile:
        """Parse a file and return structured data.

        Args:
            path: Path to the file to parse.

        Returns:
            ParsedFile with headers, rows, and metadata.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file format is invalid.
        """
        ...

    def can_parse(self, path: Path) -> bool:
        """Check if this parser can handle the given file.

        Args:
            path: Path to check.

        Returns:
            True if this parser can handle the file.
        """
        ...

    def iter_dicts(self, path: Path) -> Iterator[dict[str, str]]:
        """Yield row dictionaries one by one for memory efficiency.

        Args:
            path: Path to the file to parse.

        Yields:
            Row dictionaries mapping header → value.
        """
        ...
