"""
Shared types for import services.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, TypeAlias, TypedDict

from core.importer.security import import_security_limits
from server.services.import_review_collector import ImportReviewCollector

RECOVERABILITY_AUTO = "auto_recoverable"
RECOVERABILITY_REVIEW = "review_recoverable"
RECOVERABILITY_BLOCKING = "blocking"

RECOVERY_SOURCE_MASTER_ALIAS = "master_alias"
RECOVERY_SOURCE_AGENCY_ALIAS_TRUSTED = "agency_alias_trusted"
RECOVERY_SOURCE_AGENCY_ALIAS_SHADOW = "agency_alias_shadow"
RECOVERY_SOURCE_LOCATION_CONTEXT = "location_context"
RECOVERY_SOURCE_PARENT_CONTEXT = "parent_context"
RECOVERY_SOURCE_BUNDLE_CONTEXT = "bundle_context"
RECOVERY_SOURCE_FUZZY_MASTER = "fuzzy_master"

ALIAS_DOMAIN_LOCATION = "location"
ALIAS_DOMAIN_PROPERTY_TYPE = "property_type"
ALIAS_DOMAIN_ACTION = "action"
ALIAS_DOMAIN_HEADER = "header"
ALIAS_DOMAIN_PRICE = "price"


class ReviewRowBuffer(ImportReviewCollector):
    """Review row buffer that also tracks emergency overflow state."""

    def __init__(self) -> None:
        super().__init__(
            max_items_emergency=import_security_limits().max_review_items_emergency,
            diagnostic_limit=50,
        )


class ReviewFieldPayload(TypedDict, total=False):
    field: str
    original: object
    normalized: object
    confidence: float
    remark: str
    metadata: dict[str, object]


class ReviewFieldDiffPayload(TypedDict):
    changed_mutable: list[dict[str, object]]
    changed_immutable: list[dict[str, object]]
    unchanged: list[dict[str, object]]


class ReviewCandidatePayload(TypedDict, total=False):
    id: int
    row_version: int
    family_name: str
    phone: str
    remarks: str
    status: str
    match_confidence: float
    match_reasons: list[str]
    field_diffs: list[dict[str, object]]
    field_diff: ReviewFieldDiffPayload
    snapshot: dict[str, object]


class ReviewRowPayload(TypedDict, total=False):
    row: int
    data: dict[str, object]
    normalized_data: dict[str, object]
    original: dict[str, object]
    raw_data: dict[str, object]
    entity_type: str
    topology_side: str
    decision_options: list[str]
    suggested_action: str
    suggested_existing_id: int
    candidate_version: int
    suggested_confidence: float
    suggested_reasons: list[str]
    candidate_matches: list[ReviewCandidatePayload]
    candidate_total_count: int
    candidate_matches_truncated: bool
    mutable_fields: list[str]
    immutable_fields: list[str]
    field_diff: ReviewFieldDiffPayload
    review_fields: list[ReviewFieldPayload]
    remarks: list[str]
    inline_editable: bool
    immutable_conflict: bool
    recoverability_class: str
    recovered_fields: list[dict[str, object]]
    recovery_candidates: list[dict[str, object]]
    blocking_reasons: list[object]
    learning_signal_eligible: bool
    quick_fix_actions: list[dict[str, object]]
    bulk_fix_groups: list[dict[str, object]]
    reclassify_options: list[str]
    issue_group: str
    issue_title: str
    issue_summary: str
    item_id: int
    group_key: str
    status: str
    group_resolvable: bool
    group_resolution_blockers: list[str]
    resolution_source: str
    effective_action: str | None
    metadata: dict[str, object]


class ReviewAuditEntryPayload(TypedDict, total=False):
    row: int
    entity_type: str
    action: str
    target_table: str
    existing_id: int
    row_version: int
    suggested_action: str
    suggested_existing_id: int
    suggested_confidence: float
    suggested_reasons: list[object]
    payload: dict[str, object]
    before_payload: dict[str, object]
    diff_payload: dict[str, object]
    correction_payload: dict[str, object]
    candidate_count: int
    selected_candidate: ReviewCandidatePayload
    selected_field_diffs: list[object]
    remarks: list[object]


class ReviewResolutionPayload(TypedDict, total=False):
    action: str
    entity_type: str
    existing_id: int
    row_version: int
    corrections: dict[str, object]


class ReviewGroupPayload(TypedDict, total=False):
    group_key: str
    group_kind: str
    issue_group: str
    issue_title: str
    issue_summary: str
    entity_type: str
    topology_side: str
    root_label: str
    root_identity: dict[str, object]
    item_count: int
    pending_item_count: int
    blocking_item_count: int
    suggested_group_action: str
    status: str
    sample_rows: list[object]
    apply_to_all_allowed: bool
    apply_to_all_count: int
    consistent_existing_id: int | None
    resolution_template: dict[str, object]
    resolved_item_count: int
    metadata: dict[str, object]


class ReviewPagePayload(TypedDict):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


ReviewRows: TypeAlias = ReviewRowBuffer | list[ReviewRowPayload]


@dataclass
class ImportResult:
    """Result of an import operation."""

    success: bool
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    unchanged_count: int = 0
    error_count: int = 0
    created_entity_counts: dict[str, int] = dataclass_field(default_factory=dict)
    created_ids: list[int] = dataclass_field(default_factory=list)
    errors: list[dict[str, Any]] = dataclass_field(default_factory=list)
    dead_letter_summary: dict[str, int] = dataclass_field(default_factory=dict)
    result_zero_change: bool = False
    result_zero_change_reasons: list[str] = dataclass_field(default_factory=list)
    terminal_reason: str = ""


@dataclass(frozen=True)
class ImportDecision:
    """Normalized importer admission/preview decision."""

    outcome: str
    confidence: float
    detected_entity: str
    topology_side_hint: str
    bundle_mode: str
    mapping_palette_mode: str
    reason_codes: list[str] = dataclass_field(default_factory=list)
    recoverability_summary: dict[str, int] = dataclass_field(default_factory=dict)
    metrics: dict[str, Any] = dataclass_field(default_factory=dict)
    manual_mapping_required: bool = False
    manual_mapping_reasons: list[str] = dataclass_field(default_factory=list)
    review_required: bool = False
    blocking_message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "confidence": float(self.confidence),
            "detected_entity": self.detected_entity,
            "topology_side_hint": self.topology_side_hint,
            "bundle_mode": self.bundle_mode,
            "mapping_palette_mode": self.mapping_palette_mode,
            "reason_codes": list(self.reason_codes),
            "recoverability_summary": {
                str(key): int(value) for key, value in self.recoverability_summary.items()
            },
            "metrics": dict(self.metrics),
            "manual_mapping_required": bool(self.manual_mapping_required),
            "manual_mapping_reasons": list(self.manual_mapping_reasons),
            "review_required": bool(self.review_required),
            "blocking_message": self.blocking_message,
        }


@dataclass(frozen=True)
class ColumnRoleProfile:
    """Role-aware semantic profile for one detected source column."""

    header: str
    detected_type: str
    detected_role: str
    side_prior: str
    confidence: float
    reasons: list[str] = dataclass_field(default_factory=list)
    semantic_signals: dict[str, float] = dataclass_field(default_factory=dict)
    neighbor_hints: list[str] = dataclass_field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "header": self.header,
            "detected_type": self.detected_type,
            "detected_role": self.detected_role,
            "side_prior": self.side_prior,
            "confidence": float(self.confidence),
            "reasons": list(self.reasons),
            "semantic_signals": {
                str(key): float(value) for key, value in self.semantic_signals.items()
            },
            "neighbor_hints": list(self.neighbor_hints),
        }


@dataclass(frozen=True)
class SemanticEvidenceCell:
    """One non-lossy semantic evidence cell used for file-model inference."""

    header: str
    detected_type: str
    detected_role: str
    side_prior: str
    value: str
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "header": self.header,
            "detected_type": self.detected_type,
            "detected_role": self.detected_role,
            "side_prior": self.side_prior,
            "value": self.value,
            "confidence": float(self.confidence),
        }


@dataclass(frozen=True)
class SemanticEvidenceRow:
    """A non-lossy row projection for file-shape inference."""

    cells: list[SemanticEvidenceCell] = dataclass_field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"cells": [cell.as_dict() for cell in self.cells]}


@dataclass(frozen=True)
class FileModelDecision:
    """Dominant file model and side diagnostics for a parsed import file."""

    file_model_hint: str
    dominant_side: str
    dominant_side_confidence: float
    bundle_mode: str
    detected_entity: str | None
    reason_codes: list[str] = dataclass_field(default_factory=list)
    row_mixed_review_count: int = 0
    semantic_projection_conflicts: list[str] = dataclass_field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_model_hint": self.file_model_hint,
            "dominant_side": self.dominant_side,
            "dominant_side_confidence": float(self.dominant_side_confidence),
            "bundle_mode": self.bundle_mode,
            "detected_entity": self.detected_entity,
            "reason_codes": list(self.reason_codes),
            "row_mixed_review_count": int(self.row_mixed_review_count),
            "semantic_projection_conflicts": list(self.semantic_projection_conflicts),
        }


@dataclass(frozen=True)
class PriceCandidate:
    """One possible DZD-normalized interpretation for a raw price value."""

    normalized_dzd: float | None
    dialect: str
    expression_kind: str
    confidence: float
    reason_codes: list[str] = dataclass_field(default_factory=list)
    extracted_extras: dict[str, Any] = dataclass_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "normalized_dzd": self.normalized_dzd,
            "dialect": self.dialect,
            "expression_kind": self.expression_kind,
            "confidence": float(self.confidence),
            "reason_codes": list(self.reason_codes),
            "extracted_extras": dict(self.extracted_extras),
        }


@dataclass(frozen=True)
class PriceDialectDecision:
    """Column/file-level price dialect choice for ambiguous shorthand."""

    dominant_dialect: str
    confidence: float
    reason_codes: list[str] = dataclass_field(default_factory=list)
    ambiguous: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "dominant_dialect": self.dominant_dialect,
            "confidence": float(self.confidence),
            "reason_codes": list(self.reason_codes),
            "ambiguous": bool(self.ambiguous),
        }


@dataclass(frozen=True)
class PriceDialectProfile:
    """Observed dialect profile for one price-like source column."""

    header: str
    dominant_dialect: str
    confidence: float
    sample_count: int
    anchored_example_count: int
    ambiguous_example_count: int
    reason_codes: list[str] = dataclass_field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "header": self.header,
            "dominant_dialect": self.dominant_dialect,
            "confidence": float(self.confidence),
            "sample_count": int(self.sample_count),
            "anchored_example_count": int(self.anchored_example_count),
            "ambiguous_example_count": int(self.ambiguous_example_count),
            "reason_codes": list(self.reason_codes),
        }


@dataclass
class PreparedImportArtifact:
    """Prepared/planned importer spool metadata across ETL phases."""

    bundle_mode: str
    total_rows: int
    current_batch_size: int
    chunks_total: int
    temp_path: Path | None = None
    spool_dir: Path | None = None
    prepared_entries_path: Path | None = None
    root_entries_path: Path | None = None
    child_entries_path: Path | None = None
    planned_entries_path: Path | None = None
    planned_root_entries_path: Path | None = None
    planned_child_entries_path: Path | None = None
    entity_type: str = ""
    topology_side: str = "unknown"
    root_entity: str = ""
    child_entity: str = ""
    root_row_count: int = 0
    child_row_count: int = 0
    planned_row_count: int = 0
    planned_root_row_count: int = 0
    planned_child_row_count: int = 0


@dataclass
class PlannedArtifactCheckpoint:
    """Durable checkpoint for resuming a planned import load phase."""

    artifact: PreparedImportArtifact
    review_rows: ReviewRows = dataclass_field(default_factory=list)
    errors: list[dict[str, Any]] = dataclass_field(default_factory=list)
    skipped_count: int = 0
    error_count: int = 0
    review_overflow_count: int = 0


@dataclass
class ImportLoadOutcome:
    """Transactional load outcome and post-commit rebuild inputs."""

    total_db_time: float = 0.0
    listing_wilaya_ids: set[int] = dataclass_field(default_factory=set)
    demande_ids: set[int] = dataclass_field(default_factory=set)
    demande_client_ids: set[int] = dataclass_field(default_factory=set)
    offer_ids: set[int] = dataclass_field(default_factory=set)
    committed_entities: set[str] = dataclass_field(default_factory=set)


@dataclass(frozen=True)
class RecoveredField:
    field: str
    value: object
    source: str
    confidence: float
    reason: str
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "source": self.source,
            "confidence": float(self.confidence),
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RecoveryCandidate:
    field: str
    candidate_value: object
    candidate_label: str
    confidence: float
    source: str
    reason: str
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "candidate_value": self.candidate_value,
            "candidate_label": self.candidate_label,
            "confidence": float(self.confidence),
            "source": self.source,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }
