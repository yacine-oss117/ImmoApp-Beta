"""
Import metadata tests.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_importer._import_harness import ImportContext, ImportEngine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestImportMetadata:
    def test_import_metadata_present(self) -> None:
        context = ImportContext(agency_id=1, user_id=10, entity_type="client")
        engine = ImportEngine(context)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        for i, row in enumerate(result.rows):
            assert "agency_id" not in row, f"Row {i}: agency_id should not be present"
            assert "_import_batch_id" in row, f"Row {i}: missing _import_batch_id"
            assert "_import_user_id" in row, f"Row {i}: missing _import_user_id"
            assert "_import_row_index" in row, f"Row {i}: missing _import_row_index"
            assert "_import_confidence" in row, f"Row {i}: missing _import_confidence"

    def test_user_id_tracked(self) -> None:
        context = ImportContext(agency_id=1, user_id=777, entity_type="client")
        engine = ImportEngine(context)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        for row in result.rows:
            assert row["_import_user_id"] == 777
