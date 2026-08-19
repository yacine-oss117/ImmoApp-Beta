"""
Unit tests for file parsers.

Tests CSV and Excel parsing with various formats.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from core.importer.parsers.base import ParsedFile
from core.importer.parsers.csv_parser import CsvParser

# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestCsvParser:
    """Tests for CsvParser."""

    def test_can_parse_csv(self) -> None:
        """Test that parser recognizes CSV files."""
        parser = CsvParser()
        assert parser.can_parse(Path("test.csv")) is True
        assert parser.can_parse(Path("test.tsv")) is True
        assert parser.can_parse(Path("test.txt")) is True
        assert parser.can_parse(Path("test.xlsx")) is False
        assert parser.can_parse(Path("test.json")) is False

    def test_parse_simple_csv(self) -> None:
        """Test parsing a simple CSV file."""
        parser = CsvParser()
        result = parser.parse(FIXTURES_DIR / "sample_clients.csv")

        assert isinstance(result, ParsedFile)
        assert result.source_type == "csv"
        assert len(result.headers) == 6
        assert "Nom" in result.headers
        assert "Téléphone" in result.headers
        assert len(result.rows) == 4
        assert result.rows[0]["Nom"] == "Ahmed Benali"
        assert result.rows[0]["Téléphone"] == "0555123456"

    def test_parse_semicolon_delimiter(self) -> None:
        """Test auto-detection of semicolon delimiter."""
        parser = CsvParser()
        result = parser.parse(FIXTURES_DIR / "semicolon_delimited.csv")

        assert len(result.headers) == 4
        assert len(result.rows) == 2
        assert result.rows[0]["Nom"] == "Ahmed"
        assert result.rows[0]["Budget"] == "2.5M"

    def test_parse_tsv(self) -> None:
        """Test parsing tab-separated file."""
        parser = CsvParser()
        result = parser.parse(FIXTURES_DIR / "no_headers.tsv")

        # First row becomes headers (since we treat first row as header)
        assert len(result.rows) == 2

    def test_explicit_delimiter(self) -> None:
        """Test specifying delimiter explicitly."""
        parser = CsvParser(delimiter=";")
        result = parser.parse(FIXTURES_DIR / "semicolon_delimited.csv")

        assert len(result.rows) == 2
        assert result.rows[0]["Nom"] == "Ahmed"

    def test_file_not_found(self) -> None:
        """Test error when file doesn't exist."""
        parser = CsvParser()
        with pytest.raises(FileNotFoundError):
            parser.parse(Path("nonexistent.csv"))

    def test_skip_rows(self) -> None:
        """Test skipping rows before header."""
        parser = CsvParser(skip_rows=1)
        result = parser.parse(FIXTURES_DIR / "sample_clients.csv")

        # Skipping first row, so second row becomes header
        assert result.rows[0].get("Ahmed Benali") is not None or len(result.rows) == 3

    def test_max_rows(self) -> None:
        """Test limiting number of rows read."""
        parser = CsvParser(max_rows=2)
        result = parser.parse(FIXTURES_DIR / "sample_clients.csv")

        # Header + 1 data row max
        assert len(result.rows) <= 2
        assert "max_rows limit" in " ".join(result.warnings)

    def test_empty_rows_skipped(self) -> None:
        """Test that empty rows are skipped."""
        parser = CsvParser()
        result = parser.parse(FIXTURES_DIR / "sample_clients.csv")

        # All rows should have content
        for row in result.rows:
            assert any(v.strip() for v in row.values())

    def test_parse_prefers_real_delimiter_over_quoted_pipe(self, tmp_path: Path) -> None:
        path = tmp_path / "quoted_pipe.csv"
        path.write_text(
            'Nom;Ville;Budget\nAhmed;"Alger | Oran";2500000\nKarim;"Blida | Tipaza";3500000\n',
            encoding="utf-8",
        )

        parser = CsvParser()
        result = parser.parse(path)

        assert result.headers == ["Nom", "Ville", "Budget"]
        assert result.rows[0]["Ville"] == "Alger | Oran"
        assert result.rows[1]["Budget"] == "3500000"

    def test_parse_uses_single_text_open_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "single_pass.csv"
        path.write_text("Nom,Budget\nAhmed,2500000\nKarim,3500000\n", encoding="utf-8")

        parser = CsvParser()
        monkeypatch.setattr(parser, "_detect_encoding", lambda _path: "utf-8")
        open_calls: list[str] = []
        original_open: Callable[..., object] = Path.open

        def counting_open(self: Path, *args: object, **kwargs: object) -> object:
            mode = str(args[0] if args else kwargs.get("mode", "r"))
            open_calls.append(mode)
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", counting_open)

        result = parser.parse(path)

        assert result.row_count == 2
        assert open_calls.count("r") == 1


class TestParsedFile:
    """Tests for ParsedFile dataclass."""

    def test_row_count_auto_calculated(self) -> None:
        """Test that row_count is auto-calculated if not provided."""
        pf = ParsedFile(
            headers=["a", "b"],
            rows=[{"a": "1", "b": "2"}, {"a": "3", "b": "4"}],
            source_type="csv",
            source_path=Path("test.csv"),
        )
        assert pf.row_count == 2

    def test_warnings_default_empty(self) -> None:
        """Test that warnings defaults to empty list."""
        pf = ParsedFile(
            headers=[],
            rows=[],
            source_type="csv",
            source_path=Path("test.csv"),
        )
        assert pf.warnings == []


# Excel parser tests require openpyxl and a real Excel file
# We'll add those when we have a test Excel file
class TestExcelParser:
    """Tests for ExcelParser (requires openpyxl)."""

    def test_can_parse_excel(self) -> None:
        """Test that parser recognizes Excel files."""
        from core.importer.parsers.excel import ExcelParser

        parser = ExcelParser()
        assert parser.can_parse(Path("test.xlsx")) is True
        assert parser.can_parse(Path("test.xls")) is False
        assert parser.can_parse(Path("test.xlsm")) is False
        assert parser.can_parse(Path("test.csv")) is False

    def test_file_not_found(self) -> None:
        """Test error when file doesn't exist."""
        from core.importer.parsers.excel import ExcelParser

        parser = ExcelParser()
        with pytest.raises(FileNotFoundError):
            parser.parse(Path("nonexistent.xlsx"))
