"""Shared import job/public status resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

OVERFLOW_REVIEW_DISABLED_REASON = "This import produced more unresolved review items than the system can safely process in one job."


@dataclass(frozen=True)
class ResolvedImportStatus:
    job_status: str
    job_stage: str
    public_status: str
    public_stage: str
    overflow_blocking: bool
    review_disabled: bool
    review_disabled_reason: str
    terminal_error_count: int


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip() or "0")
        except ValueError:
            return 0
    return 0


def resolve_import_status(
    *,
    session_status: str,
    session_stage: str,
    progress: int,
    progress_detail: Mapping[str, object] | None,
    result_summary: Mapping[str, object] | None,
    review_visible_count: int,
) -> ResolvedImportStatus:
    normalized_status = str(session_status or "").strip().lower()
    normalized_stage = str(session_stage or "").strip().lower()
    progress_payload = dict(progress_detail or {})
    summary_payload = dict(result_summary or {})
    phase = (
        str(progress_payload.get("phase", normalized_stage or "executing") or "executing")
        .strip()
        .lower()
    )
    review_state = (
        str(
            summary_payload.get("review_state", "")
            or progress_payload.get("review_state", "")
            or "none"
        )
        .strip()
        .lower()
    )
    review_overflow_count = max(
        _coerce_int(summary_payload.get("review_overflow_count", 0)),
        _coerce_int(progress_payload.get("review_overflow_count", 0)),
    )
    overflow_blocking = bool(
        summary_payload.get("overflow_blocking", False)
        or progress_payload.get("overflow_blocking", False)
        or review_overflow_count > 0
        or review_state == "emergency_overflow"
    )
    review_disabled = bool(
        summary_payload.get("review_disabled", False)
        or progress_payload.get("review_disabled", False)
        or overflow_blocking
    )
    review_disabled_reason = str(
        summary_payload.get("review_disabled_reason", "")
        or progress_payload.get("review_disabled_reason", "")
        or (OVERFLOW_REVIEW_DISABLED_REASON if overflow_blocking else "")
        or ""
    )
    terminal_error_count = max(
        _coerce_int(summary_payload.get("error_count", 0)),
        _coerce_int(progress_payload.get("error_count", 0)),
    )

    public_status = normalized_status
    if normalized_status == "queued":
        public_status = "queued"
    if overflow_blocking:
        public_status = "failed"
    if (
        not overflow_blocking
        and normalized_status == "ready"
        and (normalized_stage == "review" or int(review_visible_count or 0) > 0)
    ):
        public_status = "review"
    elif (
        not overflow_blocking
        and normalized_status == "ready"
        and normalized_stage == "execution"
        and int(review_visible_count or 0) <= 0
        and (bool(summary_payload.get("success")) or phase == "done" or int(progress or 0) >= 100)
    ):
        public_status = "completed"
    if (
        not overflow_blocking
        and int(review_visible_count or 0) <= 0
        and terminal_error_count > 0
        and not bool(summary_payload.get("success", False))
        and public_status not in {"queued", "running", "review"}
    ):
        public_status = "failed"

    public_stage = "mapping"
    if normalized_status in {"pending", "parsing"}:
        public_stage = "upload" if normalized_stage == "upload" else "mapping"
    elif overflow_blocking:
        public_stage = "review"
    elif normalized_stage == "review" or int(review_visible_count or 0) > 0:
        public_stage = "review"
    elif normalized_status == "queued":
        public_stage = "executing"
    elif normalized_status == "running":
        public_stage = "rebuild" if phase == "rebuild" else "executing"
    elif normalized_status == "completed":
        public_stage = "done"
    elif public_status in {"completed", "failed"}:
        public_stage = "done"
    elif normalized_status == "failed":
        public_stage = phase or "executing"

    return ResolvedImportStatus(
        job_status=normalized_status,
        job_stage=normalized_stage,
        public_status=public_status,
        public_stage=public_stage,
        overflow_blocking=overflow_blocking,
        review_disabled=review_disabled,
        review_disabled_reason=review_disabled_reason,
        terminal_error_count=terminal_error_count,
    )


__all__ = [
    "OVERFLOW_REVIEW_DISABLED_REASON",
    "ResolvedImportStatus",
    "resolve_import_status",
]
