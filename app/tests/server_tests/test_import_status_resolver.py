from __future__ import annotations

from server.services.import_status_resolver import (
    OVERFLOW_REVIEW_DISABLED_REASON,
    resolve_import_status,
)


def test_resolve_import_status_projects_review_state_from_ready_review_job() -> None:
    resolved = resolve_import_status(
        session_status="ready",
        session_stage="review",
        progress=42,
        progress_detail={"phase": "review"},
        result_summary={"success": False},
        review_visible_count=3,
    )

    assert resolved.job_status == "ready"
    assert resolved.job_stage == "review"
    assert resolved.public_status == "review"
    assert resolved.public_stage == "review"
    assert resolved.overflow_blocking is False


def test_resolve_import_status_projects_failed_terminal_state_without_review() -> None:
    resolved = resolve_import_status(
        session_status="completed",
        session_stage="execution",
        progress=63,
        progress_detail={"phase": "done", "error_count": 1},
        result_summary={"success": False, "error_count": 1, "review_total_count": 0},
        review_visible_count=0,
    )

    assert resolved.public_status == "failed"
    assert resolved.public_stage == "done"
    assert resolved.terminal_error_count == 1


def test_resolve_import_status_marks_overflow_as_failed_review_block() -> None:
    resolved = resolve_import_status(
        session_status="failed",
        session_stage="review",
        progress=100,
        progress_detail={"review_state": "emergency_overflow"},
        result_summary={"overflow_blocking": True},
        review_visible_count=12,
    )

    assert resolved.public_status == "failed"
    assert resolved.public_stage == "review"
    assert resolved.review_disabled is True
    assert resolved.review_disabled_reason == OVERFLOW_REVIEW_DISABLED_REASON


def test_resolve_import_status_inferrs_overflow_from_review_overflow_count() -> None:
    resolved = resolve_import_status(
        session_status="ready",
        session_stage="review",
        progress=42,
        progress_detail={"phase": "review", "review_overflow_count": 4},
        result_summary={"review_overflow_count": 4},
        review_visible_count=1,
    )

    assert resolved.public_status == "failed"
    assert resolved.public_stage == "review"
    assert resolved.overflow_blocking is True
    assert resolved.review_disabled is True
