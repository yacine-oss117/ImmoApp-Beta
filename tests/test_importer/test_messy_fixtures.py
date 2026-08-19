"""Smoke test for messy Excel fixture import."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_importer._import_harness import ImportContext, ImportEngine


def test_messy_fixture_import_runs() -> None:
    xlsx_path = Path("tests/test_importer/fixtures/messy_data.xlsx")
    if not xlsx_path.exists():
        pytest.skip("messy_data.xlsx not found")

    context = ImportContext(agency_id=42, user_id=7, entity_type="client")
    engine = ImportEngine(context, skip_rows=3)
    result = engine.import_file(xlsx_path)

    assert result.success
    assert result.stats.total_rows > 0
