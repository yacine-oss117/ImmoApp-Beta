"""Typed contracts for importer public status projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol


class ImportStatusSession(Protocol):
    id: object
    task_id: object
    status: object
    stage: object
    progress: object
    error_message: object
    result_summary: Mapping[str, object] | None
    progress_detail: Mapping[str, object] | None
    inference_summary: Mapping[str, object] | None
    preview_rows: Sequence[Mapping[str, object]] | None
    review_rows: Sequence[Mapping[str, object]] | None
    detected_columns: Sequence[Mapping[str, object]] | None
    detected_entity: object
    column_mapping: Mapping[str, str] | None


class ReviewSnapshotProtocol(Protocol):
    visible_review_count: int
    pending_group_count: int
    conflict_count: int
    issue_counts: Mapping[str, int]


class RuntimeProfileProtocol(Protocol):
    name: str


class ResolvedImportStatusProtocol(Protocol):
    public_status: str
    public_stage: str
    overflow_blocking: bool
    review_disabled: bool
    review_disabled_reason: str
    terminal_error_count: int


class WorkflowPayloadFn(Protocol):
    def __call__(self, session: ImportStatusSession) -> Mapping[str, object]: ...


class EnsureReviewStateFn(Protocol):
    def __call__(self, session: ImportStatusSession) -> ReviewSnapshotProtocol | None: ...


class ReviewCountSnapshotFn(Protocol):
    def __call__(self, session: ImportStatusSession) -> ReviewSnapshotProtocol: ...


class ResolveImportStatusFn(Protocol):
    def __call__(
        self,
        *,
        session_status: str,
        session_stage: str,
        progress: int,
        progress_detail: Mapping[str, object] | None,
        result_summary: Mapping[str, object] | None,
        review_visible_count: int,
    ) -> ResolvedImportStatusProtocol: ...


class RuntimeProfileFn(Protocol):
    def __call__(self) -> RuntimeProfileProtocol: ...


class BudgetStateSnapshotFn(Protocol):
    def __call__(
        self,
        *,
        agency_ids: list[int],
        budget_names: list[str],
    ) -> Mapping[str, object]: ...


class ExecutionHealthSnapshotFn(Protocol):
    def __call__(self, session: ImportStatusSession) -> Mapping[str, object]: ...


class QueuePositionForJobFn(Protocol):
    def __call__(self, session: ImportStatusSession) -> int: ...


class CanonicalizeColumnMappingFn(Protocol):
    def __call__(
        self,
        *,
        column_mapping: dict[str, str] | None,
        detected_columns: list[dict[str, object]] | None,
        final_inference: Mapping[str, object] | None = None,
    ) -> dict[str, str]: ...


class DeriveMappingPaletteFn(Protocol):
    def __call__(
        self,
        *,
        final_inference: Mapping[str, object],
        detected_columns: Sequence[Mapping[str, object]],
        column_mapping: Mapping[str, str] | None = None,
        manual_mapping_required: bool = False,
        detected_entity: str = "",
        sheet_profiles: Sequence[Mapping[str, object]] | None = None,
        selected_sheet_name: str = "",
    ) -> dict[str, object]: ...


class LiveAgencyQueueDepthFn(Protocol):
    def __call__(self, *, agency_id: int, session_status: str) -> int: ...


__all__ = [
    "BudgetStateSnapshotFn",
    "CanonicalizeColumnMappingFn",
    "DeriveMappingPaletteFn",
    "EnsureReviewStateFn",
    "ExecutionHealthSnapshotFn",
    "ImportStatusSession",
    "LiveAgencyQueueDepthFn",
    "QueuePositionForJobFn",
    "ResolveImportStatusFn",
    "ResolvedImportStatusProtocol",
    "ReviewCountSnapshotFn",
    "ReviewSnapshotProtocol",
    "RuntimeProfileFn",
    "RuntimeProfileProtocol",
    "WorkflowPayloadFn",
]
