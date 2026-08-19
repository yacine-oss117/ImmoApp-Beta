from __future__ import annotations

from types import SimpleNamespace

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.services.import_review_compatibility import enrich_review_items  # noqa: E402
from server.services.import_review_payloads import (  # noqa: E402
    build_review_capacity_exceeded_response,
    build_review_duplicate_conflict_response,
    prepare_effective_review_submit_payload,
)


def _job() -> object:
    return SimpleNamespace(
        id="job-1",
        inference_summary={
            "final_inference": {
                "bundle_mode": "single_entity",
                "topology_side_hint": "client_side",
            }
        },
        progress_detail={},
        result_summary={},
    )


def test_enrich_review_items_preserves_review_item_and_legacy_row_shapes() -> None:
    review_items = [
        {
            "item_id": 15,
            "group_key": "group-1",
            "row": 7,
            "entity_type": "client",
            "topology_side": "client_side",
            "issue_group": "missing_information",
            "issue_title": "Missing information",
            "issue_summary": "Needs details.",
            "raw_data": {"family_name": "Alpha", "phone": "0555001001"},
            "normalized_data": {"family_name": "Alpha", "phone": "0555001001"},
            "candidate_matches": [],
            "review_fields": [],
            "recovered_fields": [],
            "recovery_candidates": [],
            "blocking_reasons": [],
            "suggested_action": "review_ambiguous",
            "suggested_existing_id": 0,
            "suggested_confidence": 0.0,
            "quick_fix_actions": [{"field": "phone", "label": "Use phone", "candidate_value": "1"}],
            "bulk_fix_groups": [
                {"group_key": "phone:1", "target_rows": [7], "occurrence_count": 1}
            ],
            "inline_editable": True,
            "immutable_conflict": False,
            "recoverability_class": "review_recoverable",
            "status": "pending",
            "group_resolvable": False,
            "group_resolution_blockers": [],
            "resolution_source": "",
            "effective_action": None,
        }
    ]

    normalized_items, legacy_rows = enrich_review_items(job=_job(), review_items=review_items)

    assert len(normalized_items) == 1
    assert len(legacy_rows) == 1
    assert normalized_items[0]["item_id"] == 15
    assert legacy_rows[0]["item_id"] == 15
    assert legacy_rows[0]["group_key"] == "group-1"
    assert legacy_rows[0]["data"] == {"family_name": "Alpha", "phone": "0555001001"}
    assert legacy_rows[0]["normalized_data"] == {"family_name": "Alpha", "phone": "0555001001"}
    assert legacy_rows[0]["raw_data"] == {"family_name": "Alpha", "phone": "0555001001"}
    assert normalized_items[0]["quick_fix_actions"] == legacy_rows[0]["quick_fix_actions"]
    assert normalized_items[0]["bulk_fix_groups"] == legacy_rows[0]["bulk_fix_groups"]


def test_prepare_effective_review_submit_payload_promotes_plain_row_keys_and_defaults_review() -> (
    None
):
    pending_rows = [
        {
            "row": 4,
            "entity_type": "client",
            "data": {"family_name": "Alpha"},
            "normalized_data": {"family_name": "Alpha"},
        }
    ]

    prepared = prepare_effective_review_submit_payload(
        pending_rows=pending_rows,
        corrections={"4": {"family_name": "Alpha Edited"}},
        decisions={},
        skip_rows=[],
        bulk_operations=[],
    )

    assert prepared.corrections == {"4:client": {"family_name": "Alpha Edited"}}
    assert prepared.decisions == {"4:client": {"action": "review_ambiguous"}}
    assert prepared.skip_rows == []


def test_capacity_and_duplicate_conflict_builders_preserve_contract_keys() -> None:
    job = SimpleNamespace(id="job-7")

    capacity = build_review_capacity_exceeded_response(job=job, review_state="emergency_overflow")
    duplicate = build_review_duplicate_conflict_response(
        job=job,
        detail="duplicate",
        row_conflicts=[{"row": 9, "entity_type": "client"}],
        conflict_groups=["group-1"],
        conflict_item_ids=[101],
        correlation_id="corr-1",
        snapshot=SimpleNamespace(visible_review_count=2),
        review_state="normal",
    )

    assert capacity == {
        "code": "IMPORT_REVIEW_CAPACITY_EXCEEDED",
        "detail": "This import produced more unresolved review items than the system can safely process in one job.",
        "session_id": "job-7",
        "review_state": "emergency_overflow",
        "overflow_blocking": True,
        "review_disabled": True,
        "review_disabled_reason": "This import produced more unresolved review items than the system can safely process in one job.",
    }
    assert duplicate["code"] == "IMPORT_REVIEW_DUPLICATE_CONFLICT"
    assert duplicate["detail"] == "duplicate"
    assert duplicate["row_conflicts"] == [{"row": 9, "entity_type": "client"}]
    assert duplicate["conflict_groups"] == ["group-1"]
    assert duplicate["conflict_item_ids"] == [101]
    assert duplicate["correlation_id"] == "corr-1"
    assert duplicate["session_id"] == "job-7"
    assert duplicate["review_count"] == 2
