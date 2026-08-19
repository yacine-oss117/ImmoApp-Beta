from __future__ import annotations

import csv
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from core.importer.parsers import CsvParser, ExcelParser, OdsParser

try:
    import openpyxl  # noqa: F401

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    import odf  # noqa: F401

    HAS_ODFPY = True
except ImportError:
    HAS_ODFPY = False


def _write_messy_csv(path: Path, rows: int = 1000) -> None:
    headers = ["Nom", "Telephone", "Budget", "Commune", "Notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(headers)
        for i in range(rows):
            writer.writerow(
                [
                    f"Märçô {i}",
                    f"+213 555 12{i % 100:02d}",
                    "2,5M" if i % 2 == 0 else "1.200.000",
                    "Hydra" if i % 3 else "بن عكنون",
                    "<script>alert(1)</script>" if i % 50 == 0 else "normal",
                ]
            )


def test_csv_parser_handles_messy_data_fast() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "messy.csv"
        _write_messy_csv(path, rows=1000)
        parser = CsvParser()

        start = time.perf_counter()
        parsed = parser.parse(path)
        elapsed = time.perf_counter() - start

        assert parsed.row_count == 1000
        assert parsed.headers[:3] == ["Nom", "Telephone", "Budget"]
        assert len(parsed.rows) > 0
        assert elapsed < 5.0


@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl not installed")
def test_excel_parser_handles_messy_data_fast() -> None:
    import openpyxl

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "messy.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Nom", "Telephone", "Budget", "Commune", "Notes"])
        for i in range(1000):
            ws.append(
                [
                    f"Märçô {i}",
                    f"0555-12{i % 100:02d}",
                    "2500000",
                    "Hydra" if i % 2 else "El Biar",
                    "normal",
                ]
            )
        wb.save(path)
        wb.close()

        parser = ExcelParser()
        start = time.perf_counter()
        parsed = parser.parse(path)
        elapsed = time.perf_counter() - start

        assert parsed.row_count >= 1000
        assert parsed.headers[:3] == ["Nom", "Telephone", "Budget"]
        assert len(parsed.rows) > 0
        assert elapsed < 5.0


@pytest.mark.skipif(not HAS_ODFPY, reason="odfpy not installed")
def test_ods_parser_handles_messy_data_fast() -> None:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "messy.ods"
        doc = OpenDocumentSpreadsheet()
        table = Table(name="Sheet1")

        header_row = TableRow()
        for h in ["Nom", "Telephone", "Budget", "Commune", "Notes"]:
            cell = TableCell()
            cell.addElement(P(text=h))
            header_row.addElement(cell)
        table.addElement(header_row)

        for i in range(1000):
            row = TableRow()
            values = [
                f"Märçô {i}",
                f"0555{i % 100:02d}1234",
                "2500000",
                "Hydra" if i % 2 else "بن عكنون",
                "normal",
            ]
            for value in values:
                cell = TableCell()
                cell.addElement(P(text=value))
                row.addElement(cell)
            table.addElement(row)
        doc.spreadsheet.addElement(table)
        doc.save(str(path))

        parser = OdsParser()
        start = time.perf_counter()
        parsed = parser.parse(path)
        elapsed = time.perf_counter() - start

        assert parsed.row_count >= 1000
        assert parsed.headers[:3] == ["Nom", "Telephone", "Budget"]
        assert len(parsed.rows) > 0
        assert elapsed < 5.0
