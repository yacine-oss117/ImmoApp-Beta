from __future__ import annotations

from pathlib import Path

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.api import tasks_import_parse as tasks_import_parse_module  # noqa: E402
from server.api.import_helpers import get_parser_for_file  # noqa: E402
from server.services.import_column_semantics import (  # noqa: E402
    build_semantic_evidence_rows,
    detected_columns_with_semantics,
)
from server.services.import_type_inference import (  # noqa: E402
    infer_file_type,
    infer_row_entity,
)


def test_infer_row_entity_keeps_weak_same_row_bundle_child_rows_as_child() -> None:
    result = infer_row_entity(
        {
            "family_name": "Yacine",
            "phone": "0555 001 001",
            "locations": "Hydra",
        },
        bundle_mode="same_side_bundle",
        default_entity_type="client",
        topology_side_hint="client_side",
    )

    assert result.entity_type == "demande"
    assert result.topology_side == "client_side"


def test_infer_row_entity_rejects_cross_side_contamination_inside_same_side_bundle() -> None:
    result = infer_row_entity(
        {
            "family_name": "Contaminated",
            "phone": "0555 001 009",
            "budget": "12000000",
            "location": "Hydra",
            "link": "https://example.test/listing/1",
        },
        bundle_mode="same_side_bundle",
        default_entity_type="client",
        topology_side_hint="client_side",
    )

    assert result.entity_type is None
    assert "listing-side signals" in " ".join(result.reasons)


def test_infer_file_type_detects_same_side_bundle_from_semantic_rows_without_exclusive_headers() -> (
    None
):
    inference = infer_file_type(
        headers=["family_name", "phone", "status", "locations"],
        sample_rows=[
            {
                "family_name": "Yacine",
                "phone": "0555 001 001",
                "status": "active",
                "locations": "Hydra",
            }
        ],
        ui_hint=None,
    )

    final_inference = dict(inference.get("final_inference", {}) or {})
    assert final_inference["bundle_mode"] == "same_side_bundle"
    assert final_inference["detected_entity"] == "client"
    assert final_inference["topology_side_hint"] == "client_side"


def test_semantic_inference_inputs_project_detected_columns_for_parse_time_row_scoring() -> None:
    headers, rows = tasks_import_parse_module._semantic_inference_inputs(
        detected_columns=[
            {"header": "Nom", "detected_type": "family_name"},
            {"header": "Telephone", "detected_type": "phone"},
            {"header": "Quartiers", "detected_type": "locations"},
            {"header": "Ignored", "detected_type": "unknown"},
        ],
        sample_rows=[
            {
                "Nom": "Yacine",
                "Telephone": "0555 001 001",
                "Quartiers": "Hydra",
                "Ignored": "noise",
            }
        ],
    )

    assert headers == ["family_name", "phone", "locations"]
    assert rows == [
        {
            "family_name": "Yacine",
            "phone": "0555 001 001",
            "locations": "Hydra",
        }
    ]


def test_semantic_evidence_inputs_keep_duplicate_domains_without_overwrite() -> None:
    rows, conflicts = tasks_import_parse_module._semantic_evidence_inputs(
        detected_columns=[
            {
                "header": "Nom complet / Client",
                "detected_type": "name",
                "detected_role": "root_identity",
                "side_prior": "client_root",
                "confidence": 0.95,
            },
            {
                "header": "Remarques additionnelles",
                "detected_type": "notes",
                "detected_role": "root_notes",
                "side_prior": "neutral",
                "confidence": 0.92,
            },
            {
                "header": "Tags / Labels",
                "detected_type": "notes",
                "detected_role": "root_tags",
                "side_prior": "neutral",
                "confidence": 0.9,
            },
        ],
        sample_rows=[
            {
                "Nom complet / Client": "Nadia",
                "Remarques additionnelles": "urgent",
                "Tags / Labels": "vip",
            }
        ],
    )

    assert len(conflicts) == 1
    assert conflicts[0].startswith("notes: ")
    assert "Remarques additionnelles" in conflicts[0]
    assert "Tags / Labels" in conflicts[0]
    assert rows == [
        {
            "cells": [
                {
                    "header": "Nom complet / Client",
                    "detected_type": "name",
                    "detected_role": "root_identity",
                    "side_prior": "client_root",
                    "value": "Nadia",
                    "confidence": 0.95,
                },
                {
                    "header": "Remarques additionnelles",
                    "detected_type": "notes",
                    "detected_role": "root_notes",
                    "side_prior": "neutral",
                    "value": "urgent",
                    "confidence": 0.92,
                },
                {
                    "header": "Tags / Labels",
                    "detected_type": "notes",
                    "detected_role": "root_tags",
                    "side_prior": "neutral",
                    "value": "vip",
                    "confidence": 0.9,
                },
            ]
        }
    ]


def test_real_chaotic_fixture_infers_client_lead_sheet() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "import_corpus" / "chaotic_fixture.xlsx"
    )
    parser, _file_type = get_parser_for_file(fixture_path.name)
    parsed = parser.parse(fixture_path)
    rows = [dict(row) for row in parsed.rows[:25]]
    detected_columns, _hints = detected_columns_with_semantics(
        headers=list(parsed.headers),
        sample_rows=rows,
        agency_id=1,
    )
    evidence_rows, conflicts = build_semantic_evidence_rows(
        detected_columns=detected_columns,
        sample_rows=rows,
    )

    inference = infer_file_type(
        headers=list(parsed.headers),
        sample_rows=[row.as_dict() for row in evidence_rows],
        ui_hint="client",
    )
    final_inference = dict(inference.get("final_inference", {}) or {})

    assert any(
        conflict.startswith("notes: ")
        and "Remarques additionnelles" in conflict
        and "Tags / Labels" in conflict
        for conflict in conflicts
    )
    assert final_inference["file_model_hint"] == "client_lead_sheet"
    assert final_inference["dominant_side"] == "client_side"
    assert final_inference["bundle_mode"] == "same_side_bundle"
    assert final_inference["detected_entity"] == "client"
