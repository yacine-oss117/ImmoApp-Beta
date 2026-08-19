"""
Normalizer regression tests for the import pipeline.
"""

from __future__ import annotations

import pytest

from core.importer.normalize_pipeline import NormalizationPipeline
from core.importer.normalizers import (
    ActionNormalizer,
    BooleanNormalizer,
    PhoneNormalizer,
    PriceNormalizer,
    PropertyTypeNormalizer,
)


class TestPhoneNormalizerRegression:
    @pytest.fixture
    def normalizer(self) -> PhoneNormalizer:
        return PhoneNormalizer()

    @pytest.mark.parametrize(
        "input_value,expected_output",
        [
            ("0555123456", "0555123456"),
            ("05 55 12 34 56", "0555123456"),
            ("05-55-12-34-56", "0555123456"),
            ("05.55.12.34.56", "0555123456"),
            ("+213555123456", "0555123456"),
            ("+213 555 123 456", "0555123456"),
            ("00213555123456", "0555123456"),
            ("555123456", "0555123456"),
            ("(0555) 12-34-56", "0555123456"),
        ],
    )
    def test_phone_normalization_exact_output(
        self,
        normalizer: PhoneNormalizer,
        input_value: str,
        expected_output: str,
    ) -> None:
        result = normalizer.normalize(input_value)
        assert (
            result.value == expected_output
        ), f"'{input_value}' must normalize to '{expected_output}', got '{result.value}'"


class TestPriceNormalizerRegression:
    @pytest.fixture
    def normalizer(self) -> PriceNormalizer:
        return PriceNormalizer()

    @pytest.mark.parametrize(
        "input_value,expected_output",
        [
            ("2500000", 2_500_000),
            ("4500000", 4_500_000),
            ("2.500.000", 2_500_000),
            ("1.800.000", 1_800_000),
            ("2 500 000", 2_500_000),
        ],
    )
    def test_price_normalization_exact_output(
        self,
        normalizer: PriceNormalizer,
        input_value: str,
        expected_output: int,
    ) -> None:
        result = normalizer.normalize(input_value)
        assert (
            result.value == expected_output
        ), f"'{input_value}' must normalize to {expected_output}, got {result.value}"

    @pytest.mark.parametrize("input_value", ["2.5M", "2,5M", "3M", "2 millions", "3 million"])
    def test_price_million_shorthand_requires_context(
        self,
        normalizer: PriceNormalizer,
        input_value: str,
    ) -> None:
        result = normalizer.normalize(input_value)
        assert result.value is None
        assert result.needs_review is True
        assert result.extracted_extras["price_ambiguity_reason_codes"] == [
            "ambiguous_million_token"
        ]


class TestPropertyTypeNormalizerRegression:
    @pytest.fixture
    def normalizer(self) -> PropertyTypeNormalizer:
        return PropertyTypeNormalizer()

    @pytest.mark.parametrize(
        "input_value,expected_type,expected_beds",
        [
            ("F3", "apartment", 3),
            ("F4", "apartment", 4),
            ("f2", "apartment", 2),
            ("F5", "apartment", 5),
            ("Villa", "villa", None),
            ("Studio", "studio", 1),
            ("Duplex", "duplex", None),
            ("terrain", "land", None),
            ("local commercial", "commercial", None),
        ],
    )
    def test_property_type_normalization_exact_output(
        self,
        normalizer: PropertyTypeNormalizer,
        input_value: str,
        expected_type: str,
        expected_beds: int | None,
    ) -> None:
        result = normalizer.normalize(input_value)
        assert (
            result.value == expected_type
        ), f"'{input_value}' must normalize to '{expected_type}', got '{result.value}'"
        assert (
            result.extracted_extras.get("beds") == expected_beds
        ), f"'{input_value}' must have beds={expected_beds}"


class TestActionNormalizerRegression:
    @pytest.mark.parametrize(
        "input_value,expected_action",
        [
            ("Achat", "buy"),
            ("achat", "buy"),
            ("acheter", "buy"),
            ("Vente", "sell"),
            ("vente", "sell"),
            ("Location", "rent"),
            ("location", "rent"),
            ("louer", "rent"),
        ],
    )
    def test_action_normalization_exact_output(
        self,
        input_value: str,
        expected_action: str,
    ) -> None:
        normalizer = ActionNormalizer()
        result = normalizer.normalize(input_value)
        assert (
            result.value == expected_action
        ), f"'{input_value}' must normalize to '{expected_action}', got '{result.value}'"


class TestBooleanNormalizerRegression:
    @pytest.fixture
    def normalizer(self) -> BooleanNormalizer:
        return BooleanNormalizer()

    @pytest.mark.parametrize(
        "input_value,expected_output",
        [
            ("oui", True),
            ("Oui", True),
            ("OUI", True),
            ("yes", True),
            ("1", True),
            ("✓", True),
            ("non", False),
            ("Non", False),
            ("no", False),
            ("0", False),
        ],
    )
    def test_boolean_normalization_exact_output(
        self,
        normalizer: BooleanNormalizer,
        input_value: str,
        expected_output: bool,
    ) -> None:
        result = normalizer.normalize(input_value)
        assert (
            result.value == expected_output
        ), f"'{input_value}' must normalize to {expected_output}, got {result.value}"

    def test_boolean_any_means_no_preference(self, normalizer: BooleanNormalizer) -> None:
        result = normalizer.normalize("any")
        assert result.value is None
        assert result.needs_review is False

    def test_boolean_semi_requires_review(self, normalizer: BooleanNormalizer) -> None:
        result = normalizer.normalize("Semi")
        assert result.value is None
        assert result.needs_review is True


class TestNormalizationPipelineNumericRegression:
    def test_room_suffixes_are_parsed_as_integer_quantities(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"rooms": "rooms", "beds": "beds", "floor": "floor"},
        )

        result = pipeline.normalize_row({"rooms": "1 room", "beds": "4 beds", "floor": "2 étage"})

        assert result.data["rooms"] == 1
        assert result.data["beds"] == 4
        assert result.data["floor"] == 2
        assert result.needs_review is False

    def test_surface_suffixes_are_parsed_as_measurements(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"surface": "surface", "surface_max": "surface_max"},
        )

        result = pipeline.normalize_row({"surface": "85m2", "surface_max": "120 m"})

        assert result.data["surface"] == 85.0
        assert result.data["surface_max"] == 120.0
        assert result.needs_review is False

    def test_surface_range_populates_both_range_fields(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"surface_max": "surface_max"},
        )

        result = pipeline.normalize_row({"surface_max": "80-120"})

        assert result.data["surface_max"] == 120.0
        assert result.data["surface_min"] == 80.0
        assert result.needs_review is False

    def test_surface_approximate_value_requires_review_but_keeps_exact_pair(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"surface_min": "surface_min"},
        )

        result = pipeline.normalize_row({"surface_min": "environ 90"})

        assert result.data["surface_min"] == 90.0
        assert result.data["surface_max"] == 90.0
        assert result.needs_review is True

    def test_beds_range_keeps_lower_bound_and_review_metadata(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"beds_min": "beds_min"},
        )

        result = pipeline.normalize_row({"beds_min": "3/4"})

        assert result.data["beds_min"] == 3
        assert result.needs_review is True
        assert result.review_fields[0].metadata["extracted_extras"]["candidate_max"] == 4

    def test_floor_range_populates_both_bounds(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"floor_min": "floor_min"},
        )

        result = pipeline.normalize_row({"floor_min": "Entre 2 et 4"})

        assert result.data["floor_min"] == 2
        assert result.data["floor_max"] == 4
        assert result.needs_review is False

    def test_ground_floor_variants_are_supported(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"floor": "floor", "floor_min": "floor_min"},
        )

        exact = pipeline.normalize_row({"floor": "RDC"})
        raised = pipeline.normalize_row({"floor_min": "rdc sur-elevé"})

        assert exact.data["floor"] == 0
        assert exact.needs_review is False
        assert raised.data["floor_min"] == 0
        assert raised.data["floor_max"] == 0
        assert raised.needs_review is True

    def test_unknown_trailing_text_still_requires_review(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"rooms": "rooms", "surface": "surface"},
        )

        result = pipeline.normalize_row({"rooms": "1 mystery", "surface": "85 strange"})

        assert result.data["rooms"] is None
        assert result.data["surface"] is None
        assert result.needs_review is True

    def test_word_numbers_and_phone_labels_are_supported(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"beds_min": "beds_min", "phone": "phone"},
        )

        result = pipeline.normalize_row({"beds_min": "trois", "phone": "Phone: 0666112233"})

        assert result.data["beds_min"] == 3
        assert result.data["phone"] == "0666112233"

    def test_price_review_metadata_keeps_interpretation_candidates(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"budget_max": "price"},
            field_metadata={"budget_max": {"source_header": "Budget"}},
        )

        result = pipeline.normalize_row({"budget_max": "1.5 M"})

        assert result.needs_review is True
        review_field = next(
            field for field in result.review_fields if field.field_name == "budget_max"
        )
        assert review_field.metadata["source_header"] == "Budget"
        assert len(review_field.metadata["interpretation_candidates"]) == 2

    def test_negative_floor_is_accepted_for_basement(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"floor": "floor"},
        )

        result = pipeline.normalize_row({"floor": "-1"})

        assert result.data["floor"] == -1
        assert result.needs_review is False

    def test_negative_floor_minus_two_basement(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"floor": "floor"},
        )

        result = pipeline.normalize_row({"floor": "-2"})

        assert result.data["floor"] == -2
        assert result.needs_review is False

    def test_comma_thousand_separator_not_decimal(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"surface": "surface"},
        )

        result = pipeline.normalize_row({"surface": "1,500"})

        assert result.data["surface"] == 1500.0

    def test_extracted_extra_conflict_with_explicit_column_adds_remark(self) -> None:
        pipeline = NormalizationPipeline(
            entity_type="listing",
            column_types={"type": "type", "beds": "beds"},
        )

        result = pipeline.normalize_row({"type": "F3", "beds": "2"})

        assert result.data["beds"] == 2
        assert any("explicit column has beds=2" in remark for remark in result.remarks)
