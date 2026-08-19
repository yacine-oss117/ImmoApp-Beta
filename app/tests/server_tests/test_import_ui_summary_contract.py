from __future__ import annotations

from server.services.import_ui_summary import (
    accumulate_preview_summary_row,
    empty_attention_summary,
    empty_auto_fix_summary,
    empty_entity_counts,
    review_overflow_count_for_payload,
    review_total_count_for_payload,
    summarize_result_state,
)


def test_accumulate_preview_summary_row_counts_missing_information() -> None:
    entity_counts = empty_entity_counts()
    auto_fix_summary = empty_auto_fix_summary()
    attention_summary = empty_attention_summary()

    grouped = accumulate_preview_summary_row(
        {
            "entity_type": "client",
            "needs_review": True,
            "review_fields": [
                {
                    "field": "budget_min",
                    "remark": "Missing budget",
                }
            ],
            "remarks": ["Missing budget"],
        },
        bundle_mode="single_entity",
        entity_counts=entity_counts,
        auto_fix_summary=auto_fix_summary,
        attention_summary=attention_summary,
    )

    assert grouped == 0
    assert entity_counts["client"] == 1
    assert attention_summary["needs_attention"] == 1
    assert attention_summary["missing_information"] == 1


def test_summarize_result_state_uses_review_total_count_beyond_compatibility_sample() -> None:
    compatibility_rows = [
        {
            "row": index + 1,
            "candidate_matches": [{"id": index + 100}],
        }
        for index in range(25)
    ]

    _, _, attention_summary = summarize_result_state(
        result_summary={
            "review_total_count": 40,
            "review_overflow_count": 0,
            "error_count": 0,
        },
        review_rows=compatibility_rows,
    )

    assert attention_summary["needs_attention"] == 40
    assert attention_summary["possible_duplicates"] == 25


def test_review_overflow_count_for_payload_uses_highest_available_value() -> None:
    assert (
        review_overflow_count_for_payload(
            progress_detail={"review_overflow_count": 0},
            result_summary={"review_overflow_count": 3},
        )
        == 3
    )


def test_review_total_count_for_payload_respects_explicit_summary_total() -> None:
    assert (
        review_total_count_for_payload(
            visible_review_count=25,
            progress_detail={"review_overflow_count": 0},
            result_summary={"review_total_count": 40},
        )
        == 40
    )
