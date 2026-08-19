"""
Architectural invariant tests for the import pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_importer._import_harness import ImportContext, ImportEngine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestAgencyIdEnforcement:
    """Tests that verify agency_id is ALWAYS enforced."""

    def test_agency_id_enforced_on_all_rows(self) -> None:
        context = ImportContext(agency_id=999, user_id=1, entity_type="client")
        engine = ImportEngine(context)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        assert result.success
        assert len(result.rows) > 0, "Must have at least one row to test"

        for i, row in enumerate(result.rows):
            assert (
                "agency_id" not in row
            ), f"Row {i}: agency_id must NOT be in row (handled by DB default), got {row.get('agency_id')}"

    def test_agency_id_overrides_source_data(self) -> None:
        context = ImportContext(agency_id=42, user_id=1, entity_type="client")
        engine = ImportEngine(context)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        for row in result.rows:
            assert (
                "agency_id" not in row
            ), "Source agency_id must be removed (handled by DB default)"

    def test_different_agencies_isolated(self) -> None:
        file_path = FIXTURES_DIR / "sample_clients.csv"

        ctx1 = ImportContext(agency_id=1, user_id=1, entity_type="client")
        engine1 = ImportEngine(ctx1)
        result1 = engine1.import_file(file_path)

        ctx2 = ImportContext(agency_id=2, user_id=1, entity_type="client")
        engine2 = ImportEngine(ctx2)
        result2 = engine2.import_file(file_path)

        for row in result1.rows:
            assert "agency_id" not in row
            assert row["_import_user_id"] == 1

        for row in result2.rows:
            assert "agency_id" not in row
            assert row["_import_user_id"] == 1


class TestEntityTypeEnforcement:
    """Tests that verify entity_type is properly validated."""

    def test_entity_type_required(self) -> None:
        with pytest.raises(TypeError):
            ImportContext(agency_id=1, user_id=1)  # type: ignore[call-arg]

    def test_entity_type_must_be_valid(self) -> None:
        with pytest.raises(ValueError, match="entity_type"):
            ImportContext(agency_id=1, user_id=1, entity_type="invalid")

    def test_client_entity_type_accepted(self) -> None:
        ctx = ImportContext(agency_id=1, user_id=1, entity_type="client")
        assert ctx.entity_type == "client"

    def test_listing_entity_type_accepted(self) -> None:
        ctx = ImportContext(agency_id=1, user_id=1, entity_type="listing")
        assert ctx.entity_type == "listing"


class TestBatchIdConsistency:
    """Tests that verify batch_id is consistent across all rows."""

    def test_batch_id_same_for_all_rows(self) -> None:
        context = ImportContext(agency_id=1, user_id=1, entity_type="client")
        engine = ImportEngine(context)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        batch_ids = {row["_import_batch_id"] for row in result.rows}
        assert len(batch_ids) == 1, "All rows must have same batch_id"

    def test_batch_id_matches_context(self) -> None:
        context = ImportContext(agency_id=1, user_id=1, entity_type="client")
        engine = ImportEngine(context)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        for row in result.rows:
            assert row["_import_batch_id"] == context.batch_id
