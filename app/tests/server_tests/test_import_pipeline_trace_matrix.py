from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server.services.import_trace_snapshot import build_import_pipeline_trace

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "import_pipeline_trace"


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_expected_subset(actual: object, expected: object) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, expected_value in expected.items():
            assert key in actual
            _assert_expected_subset(actual[key], expected_value)
        return
    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected, strict=True):
            _assert_expected_subset(actual_item, expected_item)
        return
    assert actual == expected


def test_import_pipeline_trace_fixtures_cover_current_cross_layer_contract() -> None:
    fixture_paths = sorted(_FIXTURE_DIR.glob("*.json"))
    assert fixture_paths, "Import pipeline trace fixtures are missing"

    for fixture_path in fixture_paths:
        fixture = _load_fixture(fixture_path)
        expected = fixture.pop("expected")
        trace = build_import_pipeline_trace(
            upload_response=fixture.get("upload_response"),
            parse_result=fixture.get("parse_result"),
            controller_state=fixture.get("controller_state"),
            preview_response=fixture.get("preview_response"),
            execute_response=fixture.get("execute_response"),
            status_payloads=fixture.get("status_payloads"),
            review_response=fixture.get("review_response"),
            summary_state=fixture.get("summary_state"),
            tab_handoff=fixture.get("tab_handoff"),
        )
        _assert_expected_subset(trace, expected)
