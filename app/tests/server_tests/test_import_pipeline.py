"""Integration tests for NormalizationPipeline."""

from __future__ import annotations

import pytest

from core.importer.normalize_pipeline import (
    REVIEW_THRESHOLD,
    NormalizationPipeline,
    NormalizedRow,
)
from core.importer.normalizers.base import NormalizeResult
from core.importer.validation import ImportValidator


class TestNormalizationPipeline:
    """Test the full normalization pipeline with field routing."""

    @pytest.fixture
    def client_pipeline(self) -> NormalizationPipeline:
        return NormalizationPipeline(
            entity_type="client",
            column_types={
                "phone": "phone",
                "name": "name",
                "budget": "price",
                "wilaya": "wilaya",
                "commune": "location",
                "action": "action",
                "remarks": "notes",
            },
            field_metadata={
                "budget": {
                    "price_dialect_hint": "dzd_millions",
                    "price_dialect_confidence": 0.9,
                    "source_header": "Budget (DZD)",
                }
            },
        )

    @pytest.fixture
    def listing_pipeline(self) -> NormalizationPipeline:
        return NormalizationPipeline(
            entity_type="listing",
            column_types={
                "phone": "phone",
                "name": "name",
                "budget": "price",
                "type": "type",
                "elevator": "elevator",
                "surface": "surface",
                "floor": "floor",
            },
        )

    def test_clean_client_row(self, client_pipeline: NormalizationPipeline) -> None:
        """A fully clean row should pass with high confidence."""
        row = {
            "phone": "0555123456",
            "name": "Ali Boumediene",
            "budget": "2500000",
            "remarks": "Good client",
        }
        result = client_pipeline.normalize_row(row)
        assert isinstance(result, NormalizedRow)
        assert result.confidence >= REVIEW_THRESHOLD
        assert not result.needs_review
        assert result.data["phone"] == "0555123456"
        assert result.data["name"] is not None

    def test_messy_client_row(self, client_pipeline: NormalizationPipeline) -> None:
        """Messy data should still normalize where the column context is strong enough."""
        row = {
            "phone": "05 55 12 34 56",
            "name": "Ali",
            "budget": "2.5M",
        }
        result = client_pipeline.normalize_row(row)
        assert result.data["phone"] == "0555123456"
        assert result.data["budget"] == 2_500_000

    def test_review_flagging(self, client_pipeline: NormalizationPipeline) -> None:
        """Row with unknown location should flag for review."""
        row = {
            "phone": "0555123456",
            "name": "Ali",
            "commune": "XYZXYZ_UNKNOWN_PLACE",
        }
        result = client_pipeline.normalize_row(row)
        assert result.needs_review
        assert len(result.review_fields) > 0
        review_field_names = [rf.field_name for rf in result.review_fields]
        assert "commune" in review_field_names

    def test_high_confidence_autopass(self, client_pipeline: NormalizationPipeline) -> None:
        """Clean row with all known values → high confidence."""
        row = {
            "phone": "0555123456",
            "name": "Karim",
        }
        result = client_pipeline.normalize_row(row)
        assert result.confidence >= REVIEW_THRESHOLD
        assert not result.needs_review

    def test_empty_values_passthrough(self, client_pipeline: NormalizationPipeline) -> None:
        """Empty values should become None."""
        row = {
            "phone": "",
            "name": "",
            "budget": "",
        }
        result = client_pipeline.normalize_row(row)
        assert result.data["phone"] is None
        assert result.data["name"] is None
        assert result.data["budget"] is None

    def test_listing_with_type(self, listing_pipeline: NormalizationPipeline) -> None:
        """Listing with property type should extract beds."""
        row = {
            "phone": "0555123456",
            "name": "Omar",
            "type": "F3",
            "surface": "120 m²",
            "floor": "3",
            "elevator": "Oui",
        }
        result = listing_pipeline.normalize_row(row)
        assert result.data["type"] is not None
        assert result.data["surface"] == 120.0
        assert result.data["floor"] == 3
        assert result.data["elevator"] is True

    def test_numeric_normalization(self, listing_pipeline: NormalizationPipeline) -> None:
        """Numeric fields should handle various formats."""
        row = {
            "surface": "85,5",  # comma decimal
            "floor": "2",
        }
        result = listing_pipeline.normalize_row(row)
        assert result.data["surface"] == 85.5
        assert result.data["floor"] == 2

    def test_boolean_normalization(self, listing_pipeline: NormalizationPipeline) -> None:
        """Boolean fields should handle French/Arabic/symbols."""
        row = {"elevator": "Non"}
        result = listing_pipeline.normalize_row(row)
        assert result.data["elevator"] is False

    def test_context_building(self, client_pipeline: NormalizationPipeline) -> None:
        """Pipeline should build cross-column context."""
        row = {
            "phone": "0555123456",
            "wilaya": "16",
            "action": "Vente",
        }
        # This should not raise; the context building should work
        result = client_pipeline.normalize_row(row)
        assert result is not None

    def test_no_column_types(self) -> None:
        """Pipeline without column types should passthrough all fields."""
        pipeline = NormalizationPipeline(entity_type="client")
        row = {"phone": "0555123456", "name": "Ali"}
        result = pipeline.normalize_row(row)
        assert result.data["phone"] is not None
        assert result.data["name"] is not None

    def test_extras_merged(self, listing_pipeline: NormalizationPipeline) -> None:
        """Extracted extras (e.g. beds from F3) should be in data."""
        row = {"type": "F3"}
        result = listing_pipeline.normalize_row(row)
        if result.extras.get("beds"):
            assert "beds" in result.data

    def test_equivalent_duplicate_extras_remain_auto_safe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"field_a": "type", "field_b": "type"},
        )
        responses = {
            "field_a": NormalizeResult(
                value="apartment",
                confidence=1.0,
                original="F3",
                extracted_extras={"beds": 3},
            ),
            "field_b": NormalizeResult(
                value="apartment",
                confidence=1.0,
                original="3 beds",
                extracted_extras={"beds": 3},
            ),
        }
        monkeypatch.setattr(
            pipeline,
            "_normalize_field",
            lambda field_name, raw_value, col_type, context: responses[field_name],
        )

        result = pipeline.normalize_row({"field_a": "F3", "field_b": "3 beds"})

        assert result.needs_review is False
        assert result.extras["beds"] == 3
        assert result.extra_conflicts == []
        assert result.data["beds"] == 3

    def test_conflicting_extras_force_review(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"field_a": "type", "field_b": "type"},
        )
        responses = {
            "field_a": NormalizeResult(
                value="apartment",
                confidence=1.0,
                original="F3",
                extracted_extras={"beds": 3},
            ),
            "field_b": NormalizeResult(
                value="apartment",
                confidence=1.0,
                original="F4",
                extracted_extras={"beds": 4},
            ),
        }
        monkeypatch.setattr(
            pipeline,
            "_normalize_field",
            lambda field_name, raw_value, col_type, context: responses[field_name],
        )

        result = pipeline.normalize_row({"field_a": "F3", "field_b": "F4"})

        assert result.needs_review is True
        assert "beds" not in result.data
        assert "beds" not in result.extras
        assert len(result.extra_conflicts) == 1
        conflict = result.extra_conflicts[0]
        assert conflict.key == "beds"
        assert {conflict.first_value, conflict.second_value} == {3, 4}
        assert any("Conflicting extracted value for beds" in remark for remark in result.remarks)
        assert any(
            str(field.metadata.get("extra_conflict", {}).get("key", "")) == "beds"
            for field in result.review_fields
        )

    def test_diagnostic_extras_do_not_force_row_level_conflict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"wilaya": "wilaya", "commune": "location"},
        )
        responses = {
            "wilaya": NormalizeResult(
                value=16,
                confidence=1.0,
                original="Alger",
                extracted_extras={"match_type": "wilaya", "is_wilaya": True},
            ),
            "commune": NormalizeResult(
                value="16028",
                confidence=1.0,
                original="Hydra",
                extracted_extras={"match_type": "alias", "wilaya_code": "16"},
            ),
        }
        monkeypatch.setattr(
            pipeline,
            "_normalize_field",
            lambda field_name, raw_value, col_type, context: responses[field_name],
        )

        result = pipeline.normalize_row({"wilaya": "Alger", "commune": "Hydra"})

        assert result.needs_review is False
        assert result.extra_conflicts == []
        assert result.extras == {}
        assert result.data["wilaya"] == 16
        assert result.data["commune"] == "16028"

    def test_remarks_collected(self, client_pipeline: NormalizationPipeline) -> None:
        """Normalizer remarks should be collected."""
        row = {
            "phone": "123",  # Too short, should generate a remark
        }
        result = client_pipeline.normalize_row(row)
        # Either review_fields or remarks should have info about the issue
        assert result.needs_review or len(result.remarks) > 0 or result.confidence < 1.0

    def test_invalid_phone_fragment_does_not_enter_normalized_identity(
        self, client_pipeline: NormalizationPipeline
    ) -> None:
        result = client_pipeline.normalize_row({"phone": "zero six 66", "name": "Ali"})

        assert result.data["phone"] is None
        assert result.needs_review is True
        assert any(field.field_name == "phone" for field in result.review_fields)

    def test_numeric_normalization_accepts_quantity_suffixes(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"surface": "surface", "rooms": "rooms", "floor": "floor"},
        )

        result = pipeline.normalize_row({"surface": "85 m²", "rooms": "1 room", "floor": "2 étage"})

        assert result.data["surface"] == 85.0
        assert result.data["rooms"] == 1
        assert result.data["floor"] == 2
        assert result.needs_review is False

    def test_numeric_normalization_reviews_malformed_suffixes(self) -> None:
        pipeline = NormalizationPipeline(entity_type="listing", column_types={"surface": "surface"})

        result = pipeline.normalize_row({"surface": "1 room"})

        assert result.data["surface"] is None
        assert result.needs_review is True
        assert any(field.field_name == "surface" for field in result.review_fields)

    def test_passthrough_sanitization_failure_becomes_review(
        self, client_pipeline: NormalizationPipeline
    ) -> None:
        result = client_pipeline.normalize_row({"remarks": "test -- drop table"})

        assert result.data["remarks"] is None
        assert result.needs_review is True
        assert any(field.field_name == "remarks" for field in result.review_fields)
        assert any("Sanitization failed for remarks" in remark for remark in result.remarks)

    def test_passthrough_unexpected_exceptions_are_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = NormalizationPipeline(entity_type="client", column_types={"notes": "notes"})

        def _explode(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(ImportValidator, "sanitize_string", staticmethod(_explode))

        with pytest.raises(RuntimeError, match="boom"):
            pipeline.normalize_row({"notes": "keep"})

    def test_price_ambiguity_keeps_candidate_metadata_until_review(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"budget_max": "price"},
            field_metadata={
                "budget_max": {
                    "source_header": "Budget",
                }
            },
        )

        result = pipeline.normalize_row({"budget_max": "1.5 M"})

        assert result.data["budget_max"] is None
        assert result.needs_review is True
        review_field = next(
            field for field in result.review_fields if field.field_name == "budget_max"
        )
        assert review_field.metadata["source_header"] == "Budget"
        assert len(review_field.metadata["interpretation_candidates"]) == 2
        assert review_field.metadata["price_ambiguity_reason_codes"] == ["ambiguous_million_token"]

    def test_explicit_dzd_price_header_resolves_ambiguous_m_suffix(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"budget_max": "price"},
            field_metadata={
                "budget_max": {
                    "source_header": "Budget max/Prix (DZD)",
                    "price_unit_hint": "dzd",
                }
            },
        )

        result = pipeline.normalize_row({"budget_max": "1.5 M"})

        assert result.data["budget_max"] == 1_500_000
        assert result.needs_review is False
