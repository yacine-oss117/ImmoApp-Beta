from __future__ import annotations

import pytest

from app.views.imports.import_experience import (
    build_final_summary,
    build_mapping_summary,
    group_review_rows,
    review_item_from_payload,
)

pytestmark = pytest.mark.ui


def test_build_mapping_summary_uses_bundle_counts_and_friendly_copy() -> None:
    summary = build_mapping_summary(
        manual_mapping_required=False,
        import_supported=True,
        blocking_message="",
        preview_entity_counts={"client": 10, "demande": 40},
        preview_auto_fix_summary={"phone_format_fixed": 12, "grouped_related_rows": 40},
        row_count=50,
    )

    assert summary.headline == "Your columns look good"
    assert "10 clients and 40 requests" in summary.supporting_text
    assert summary.primary_counts[0].label == "Clients found"
    assert "We cleaned phone number formatting." in summary.automation_points


def test_build_mapping_summary_blocks_unsupported_child_only_import() -> None:
    summary = build_mapping_summary(
        manual_mapping_required=False,
        import_supported=False,
        blocking_message="Requests-only files aren't supported.",
        preview_entity_counts={"demande": 12},
        preview_auto_fix_summary={},
        row_count=12,
    )

    assert summary.headline == "This file needs a different import format"
    assert "requests-only files" in summary.supporting_text.lower()
    assert summary.primary_counts[0].label == "Requests found"


def test_build_final_summary_uses_business_nouns_and_attention_points() -> None:
    summary = build_final_summary(
        status="completed",
        created_count=50,
        updated_count=2,
        error_count=0,
        skipped_count=3,
        result_entity_counts={"listing": 10, "offer": 40},
        result_auto_fix_summary={"location_normalized": 8},
        result_attention_summary={"needs_attention": 3, "blocking": 1, "possible_duplicates": 2},
    )

    assert summary.headline == "Your import is almost complete"
    assert "10 properties and 40 offers" in summary.supporting_text
    assert any(metric.label == "Properties added" for metric in summary.primary_counts)
    assert "We matched cities and areas." in summary.automation_points
    assert any("existing records" in line for line in summary.attention_points)


def test_build_final_summary_uses_singular_success_grammar() -> None:
    summary = build_final_summary(
        status="completed",
        created_count=1,
        updated_count=0,
        error_count=0,
        skipped_count=0,
        result_entity_counts={"client": 1},
        result_auto_fix_summary={},
        result_attention_summary={"needs_attention": 0},
    )

    assert summary.headline == "Your import is complete"
    assert summary.supporting_text == "1 client was added to your agency."


def test_build_final_summary_uses_warning_copy_for_zero_change() -> None:
    summary = build_final_summary(
        status="completed",
        created_count=0,
        updated_count=0,
        error_count=0,
        skipped_count=5,
        result_entity_counts={},
        result_auto_fix_summary={},
        result_attention_summary={"needs_attention": 0},
        row_count=5,
        result_zero_change=True,
        result_zero_change_reasons=["all_rows_skipped"],
        terminal_reason="zero_change",
    )

    assert summary.tone == "warning"
    assert summary.headline == "Your import finished with no changes"
    assert "every line was skipped" in summary.supporting_text.lower()


def test_group_review_rows_preserves_issue_buckets() -> None:
    groups = group_review_rows(
        [
            {"row": 1, "issue_group": "possible_duplicate"},
            {"row": 2, "issue_group": "possible_duplicate"},
            {"row": 3, "issue_group": "missing_information"},
        ]
    )

    assert [group.key for group in groups] == ["possible_duplicate", "missing_information"]
    assert groups[0].title == "Possible duplicates"
    assert groups[0].count == 2


def test_review_item_from_payload_preserves_candidate_truncation_metadata() -> None:
    item = review_item_from_payload(
        {
            "item_id": 9,
            "row": 9,
            "entity_type": "client",
            "candidate_matches": [{"id": 42, "row_version": 3}],
            "candidate_total_count": 7,
            "candidate_matches_truncated": True,
        }
    )

    assert item.candidate_total_count == 7
    assert item.candidate_matches_truncated is True
    assert item.candidate_matches == [{"id": 42, "row_version": 3}]
