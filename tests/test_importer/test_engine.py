"""
Unit tests for import engine and pipeline.

Tests the full import pipeline with multi-tenant awareness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_importer._import_harness import (
    ImportContext,
    ImportEngine,
    ImportResult,
    ImportStats,
    RowTransformer,
    import_file,
)

# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestImportContext:
    """Tests for ImportContext."""

    def test_create_context(self) -> None:
        """Test creating a context."""
        ctx = ImportContext(agency_id=1, user_id=10, entity_type="client")
        assert ctx.agency_id == 1
        assert ctx.user_id == 10
        assert ctx.entity_type == "client"
        assert ctx.batch_id is not None
        assert len(ctx.batch_id) > 0

    def test_context_requires_positive_agency_id(self) -> None:
        """Test that agency_id must be positive."""
        with pytest.raises(ValueError, match="agency_id"):
            ImportContext(agency_id=0, user_id=10, entity_type="client")

    def test_context_requires_positive_user_id(self) -> None:
        """Test that user_id must be positive."""
        with pytest.raises(ValueError, match="user_id"):
            ImportContext(agency_id=1, user_id=0, entity_type="client")

    def test_dry_run_flag(self) -> None:
        """Test dry run flag."""
        ctx = ImportContext(agency_id=1, user_id=10, entity_type="client", dry_run=True)
        assert ctx.dry_run is True

    def test_entity_type_required(self) -> None:
        """Test that entity_type must be client or listing."""
        with pytest.raises(ValueError, match="entity_type"):
            ImportContext(agency_id=1, user_id=10, entity_type="invalid")


class TestImportStats:
    """Tests for ImportStats."""

    def test_success_rate_zero_rows(self) -> None:
        """Test success rate with zero rows."""
        stats = ImportStats(total_rows=0)
        assert stats.success_rate == 100.0

    def test_success_rate_calculation(self) -> None:
        """Test success rate calculation."""
        stats = ImportStats(total_rows=100, processed=95)
        assert stats.success_rate == 95.0


class TestImportResult:
    """Tests for ImportResult."""

    def test_success_no_errors(self) -> None:
        """Test success when no errors."""
        ctx = ImportContext(agency_id=1, user_id=10, entity_type="client")
        result = ImportResult(context=ctx, stats=ImportStats())
        assert result.success is True

    def test_not_success_with_errors(self) -> None:
        """Test not success when errors present."""
        ctx = ImportContext(agency_id=1, user_id=10, entity_type="client")
        result = ImportResult(context=ctx, stats=ImportStats(), errors=["Something failed"])
        assert result.success is False

    def test_has_review_items(self) -> None:
        """Test has_review_items flag."""
        ctx = ImportContext(agency_id=1, user_id=10, entity_type="client")
        result = ImportResult(context=ctx, stats=ImportStats(), review_rows=[{"a": "b"}])
        assert result.has_review_items is True


class TestRowTransformer:
    """Tests for RowTransformer."""

    @pytest.fixture
    def transformer(self) -> RowTransformer:
        """Create row transformer instance."""
        return RowTransformer()

    def test_transform_empty_row(self, transformer: RowTransformer) -> None:
        """Test transforming empty row."""
        result = transformer.transform_row({})
        assert result.data == {}
        assert result.confidence == 1.0

    def test_transform_phone_column(self, transformer: RowTransformer) -> None:
        """Test phone column detection and normalization."""
        result = transformer.transform_row({"Téléphone": "05 55 12 34 56"})
        assert result.data["Téléphone"] == "0555123456"
        assert result.confidence == 1.0

    def test_transform_price_column(self, transformer: RowTransformer) -> None:
        """Bare M shorthand should wait for a later price-dialect decision."""
        result = transformer.transform_row({"Budget": "2.5M"})
        assert result.data["Budget"] is None
        assert result.needs_review is True

    def test_transform_type_column(self, transformer: RowTransformer) -> None:
        """Test type column detection and normalization."""
        result = transformer.transform_row({"Type": "F3"})
        assert result.data["Type"] == "apartment"
        assert result.data.get("Type_beds") == 3

    def test_transform_unknown_column(self, transformer: RowTransformer) -> None:
        """Test unknown column passes through."""
        result = transformer.transform_row({"SomeCustomField": "Hello"})
        assert result.data["SomeCustomField"] == "Hello"

    def test_transform_multiple_columns(self, transformer: RowTransformer) -> None:
        """Other fields should still normalize when price scale remains ambiguous."""
        result = transformer.transform_row(
            {
                "Nom": "Ahmed",
                "Téléphone": "0555123456",
                "Budget": "3M",
                "Type": "Villa",
            }
        )
        assert result.data["Nom"] == "Ahmed"
        assert result.data["Téléphone"] == "0555123456"
        assert result.data["Budget"] is None
        assert result.data["Type"] == "villa"
        assert result.needs_review is True


class TestImportEngine:
    """Tests for ImportEngine."""

    def test_import_csv_file(self) -> None:
        """Test importing a CSV file."""
        ctx = ImportContext(agency_id=42, user_id=7, entity_type="client")
        engine = ImportEngine(ctx)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        assert result.success is True
        assert result.stats.total_rows == 4
        assert len(result.rows) + len(result.review_rows) == 4

        # CRITICAL: Verify agency_id is NOT in row (handled by DB default)
        for row in result.rows:
            assert "agency_id" not in row, "agency_id must be removed"
            assert row["_import_user_id"] == 7

    def test_agency_id_enforced(self) -> None:
        """Test that agency_id from context is enforced."""
        ctx = ImportContext(agency_id=99, user_id=1, entity_type="client")
        engine = ImportEngine(ctx)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        # Every row must NOT have agency_id
        for row in result.rows:
            assert "agency_id" not in row

    def test_batch_id_consistent(self) -> None:
        """Test that batch_id is consistent across all rows."""
        ctx = ImportContext(agency_id=1, user_id=1, entity_type="client")
        engine = ImportEngine(ctx)
        result = engine.import_file(FIXTURES_DIR / "sample_clients.csv")

        batch_ids = {row["_import_batch_id"] for row in result.rows}
        assert len(batch_ids) == 1, "All rows must have same batch_id"
        assert batch_ids.pop() == ctx.batch_id

    def test_file_not_found(self) -> None:
        """Test error when file not found."""
        ctx = ImportContext(agency_id=1, user_id=1, entity_type="client")
        engine = ImportEngine(ctx)
        result = engine.import_file(Path("nonexistent.csv"))

        assert result.success is False
        assert len(result.errors) > 0

    def test_unsupported_file_type(self) -> None:
        """Test error for unsupported file type."""
        ctx = ImportContext(agency_id=1, user_id=1, entity_type="client")
        engine = ImportEngine(ctx)
        result = engine.import_file(Path("file.pdf"))

        assert result.success is False


class TestImportFileFunction:
    """Tests for the convenience import_file function."""

    def test_import_file_function(self) -> None:
        """Test the convenience function."""
        result = import_file(
            FIXTURES_DIR / "sample_clients.csv",
            agency_id=123,
            user_id=456,
            entity_type="client",
        )

        assert result.success is True
        assert result.context.agency_id == 123
        assert result.context.user_id == 456
        assert result.context.entity_type == "client"

        for row in result.rows:
            assert "agency_id" not in row
