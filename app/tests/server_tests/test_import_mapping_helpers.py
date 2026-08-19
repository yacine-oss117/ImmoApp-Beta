from __future__ import annotations

import pytest

from server.services.import_mapping import (
    build_column_types,
    canonicalize_column_mapping,
    suggest_column_mapping,
)
from server.services.import_parsers import parser_for_file_type, parser_for_filename


def _detected(*headers: str) -> list[dict[str, object]]:
    return [{"header": h, "detected_type": "unknown"} for h in headers]


def test_canonicalize_column_mapping_keeps_field_to_header_shape() -> None:
    mapping = {"family_name": "Nom", "phone": "Telephone"}
    out = canonicalize_column_mapping(
        column_mapping=mapping,
        detected_columns=_detected("Nom", "Telephone"),
    )
    assert out == mapping


def test_canonicalize_column_mapping_inverts_legacy_header_to_field_shape() -> None:
    legacy = {"Nom": "family_name", "Telephone": "phone"}
    out = canonicalize_column_mapping(
        column_mapping=legacy,
        detected_columns=_detected("Nom", "Telephone"),
    )
    assert out == {"family_name": "Nom", "phone": "Telephone"}


def test_canonicalize_column_mapping_filters_unknown_headers() -> None:
    mapping = {"family_name": "Nom", "phone": "PhoneHeader"}
    out = canonicalize_column_mapping(
        column_mapping=mapping,
        detected_columns=_detected("Nom"),
    )
    assert out == {"family_name": "Nom"}


def test_build_column_types_overrides_status_and_remarks_to_safe_canonical_types() -> None:
    detected = [
        {"header": "status", "detected_type": "boolean"},
        {"header": "remarks", "detected_type": "unknown"},
        {"header": "family_name", "detected_type": "unknown"},
        {"header": "phone", "detected_type": "phone"},
    ]
    mapping = {
        "family_name": "family_name",
        "phone": "phone",
        "status": "status",
        "remarks": "remarks",
    }

    out = build_column_types(detected_columns=detected, column_mapping=mapping)

    assert out["family_name"] == "name"
    assert out["phone"] == "phone"
    assert out["status"] == "unknown"
    assert out["remarks"] == "notes"


def test_canonicalize_column_mapping_normalizes_same_side_bundle_semantic_aliases() -> None:
    detected_columns = [
        {
            "header": "Nom complet / Client",
            "detected_type": "name",
            "detected_role": "root_identity",
            "confidence": 1.0,
        },
        {
            "header": "N° Téléphone",
            "detected_type": "phone",
            "detected_role": "root_identity",
            "confidence": 0.9,
        },
        {
            "header": "Budget max/Prix (DZD)",
            "detected_type": "price",
            "detected_role": "child_budget_max",
            "confidence": 0.88,
        },
        {
            "header": "Surface (m2)",
            "detected_type": "surface",
            "detected_role": "child_surface",
            "confidence": 1.0,
        },
        {
            "header": "Chambres (Beds)",
            "detected_type": "rooms",
            "detected_role": "child_beds",
            "confidence": 1.0,
        },
        {
            "header": "Étage",
            "detected_type": "floor",
            "detected_role": "child_floor",
            "confidence": 1.0,
        },
        {
            "header": "Remarques additionnelles",
            "detected_type": "notes",
            "detected_role": "root_notes",
            "confidence": 1.0,
        },
    ]

    out = canonicalize_column_mapping(
        column_mapping={
            "name": "Nom complet / Client",
            "phone": "N° Téléphone",
            "price": "Budget max/Prix (DZD)",
            "surface": "Surface (m2)",
            "rooms": "Chambres (Beds)",
            "floor": "Étage",
            "notes": "Remarques additionnelles",
        },
        detected_columns=detected_columns,
        final_inference={
            "bundle_mode": "same_side_bundle",
            "topology_side_hint": "client_side",
            "file_model_hint": "client_lead_sheet",
            "detected_entity": "client",
        },
    )

    assert out == {
        "family_name": "Nom complet / Client",
        "phone": "N° Téléphone",
        "budget_max": "Budget max/Prix (DZD)",
        "surface_min": "Surface (m2)",
        "beds_min": "Chambres (Beds)",
        "floor_min": "Étage",
        "remarks": "Remarques additionnelles",
    }


def test_suggest_column_mapping_keeps_tags_and_remarks_for_client_lead_sheet() -> None:
    detected_columns = [
        {
            "header": "Tags / Labels",
            "detected_type": "notes",
            "detected_role": "root_tags",
            "confidence": 1.0,
        },
        {
            "header": "Remarques additionnelles",
            "detected_type": "notes",
            "detected_role": "root_notes",
            "confidence": 1.0,
        },
        {
            "header": "Budget max/Prix (DZD)",
            "detected_type": "price",
            "detected_role": "child_budget_max",
            "confidence": 0.88,
        },
    ]

    out = suggest_column_mapping(
        detected_columns=detected_columns,
        final_inference={
            "bundle_mode": "same_side_bundle",
            "topology_side_hint": "client_side",
            "file_model_hint": "client_lead_sheet",
            "detected_entity": "client",
        },
    )

    assert out == {
        "tags": "Tags / Labels",
        "remarks": "Remarques additionnelles",
        "budget_max": "Budget max/Prix (DZD)",
    }


def test_parser_for_filename_supports_tsv_txt_csv() -> None:
    for ext in (".csv", ".tsv", ".txt"):
        parser = parser_for_filename(f"data{ext}")
        assert parser is not None
        _, file_type = parser
        assert file_type == "csv"


def test_parser_for_file_type_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        parser_for_file_type("yaml")


def test_parser_for_filename_rejects_legacy_excel_extensions() -> None:
    assert parser_for_filename("data.xls") is None
    assert parser_for_filename("data.xlsm") is None
