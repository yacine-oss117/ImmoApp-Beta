"""
End-to-end import pipeline tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_importer._import_harness import ImportContext, ImportEngine, import_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestEndToEndImport:
    def test_sample_clients_csv_import(self) -> None:
        result = import_file(
            FIXTURES_DIR / "sample_clients.csv",
            agency_id=123,
            user_id=456,
            entity_type="client",
        )

        assert result.success
        assert result.stats.total_rows == 4
        assert result.context.agency_id == 123
        assert result.context.user_id == 456
        assert result.context.entity_type == "client"

    def test_sample_clients_xlsx_import(self) -> None:
        xlsx_path = FIXTURES_DIR / "sample_clients.xlsx"
        if not xlsx_path.exists():
            pytest.skip("sample_clients.xlsx not found")

        result = import_file(
            xlsx_path,
            agency_id=100,
            user_id=200,
            entity_type="client",
        )

        assert result.success
        for row in result.rows:
            assert "agency_id" not in row

    def test_messy_data_xlsx_import_with_skip_rows(self) -> None:
        xlsx_path = FIXTURES_DIR / "messy_data.xlsx"
        if not xlsx_path.exists():
            pytest.skip("messy_data.xlsx not found")

        context = ImportContext(agency_id=42, user_id=7, entity_type="client")
        engine = ImportEngine(context, skip_rows=3)
        result = engine.import_file(xlsx_path)

        assert result.success
        assert result.stats.total_rows >= 8, "messy_data.xlsx should have at least 8 rows"

        if result.rows:
            first_row = result.rows[0]
            budget = first_row.get("BUDGET (DA)")
            if budget is not None:
                assert isinstance(budget, int), "Budget should be normalized to int"
