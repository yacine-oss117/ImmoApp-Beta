from __future__ import annotations

import json
from pathlib import Path

from server.services.import_mapping_palette import derive_mapping_palette
from server.services.import_type_inference import infer_row_entity


def _detected_columns_from_row(row: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "header": str(key),
            "detected_type": str(key),
            "confidence": 0.95,
        }
        for key in row.keys()
    ]


def _expected_disposition(*, entity_type: object, reason_code: str) -> str:
    if reason_code == "cross_side_contamination":
        return "block"
    if entity_type is None:
        return "review"
    return "auto_execute"


def test_row_truth_matrix_cases_stay_stable() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "import_truth" / "row_truth_matrix.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert len(payload) >= 60

    for case in payload:
        result = infer_row_entity(dict(case["row"]), **dict(case["kwargs"]))
        expected = dict(case["expected"])

        assert result.entity_type == expected["entity_type"], case["name"]
        assert result.topology_side == expected["topology_side"], case["name"]

        expected_reason_code = str(expected.get("reason_code") or "").strip()
        if expected_reason_code:
            assert expected_reason_code in list(result.reason_codes or []), case["name"]

        expected_palette_mode = str(expected.get("mapping_palette_mode") or "").strip()
        if expected_palette_mode:
            kwargs = dict(case["kwargs"])
            palette = derive_mapping_palette(
                final_inference={
                    "bundle_mode": str(
                        kwargs.get("bundle_mode", "single_entity") or "single_entity"
                    ),
                    "topology_side_hint": str(
                        kwargs.get("topology_side_hint", "unknown") or "unknown"
                    ),
                    "detected_entity": str(kwargs.get("default_entity_type", "") or ""),
                },
                detected_columns=_detected_columns_from_row(dict(case["row"])),
                column_mapping=None,
                manual_mapping_required=expected_palette_mode == "recovery_union",
                detected_entity=str(kwargs.get("default_entity_type", "") or ""),
            )
            assert palette["mapping_palette_mode"] == expected_palette_mode, case["name"]

        expected_disposition = str(expected.get("disposition") or "").strip()
        if expected_disposition:
            assert (
                _expected_disposition(
                    entity_type=result.entity_type,
                    reason_code=expected_reason_code,
                )
                == expected_disposition
            ), case["name"]
