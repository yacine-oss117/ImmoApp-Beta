from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.views.imports.import_experience import (
    ImportExperienceSummary,
    ImportReviewGroupRecord,
    ImportReviewPage,
    ImportReviewPaneState,
    build_final_summary,
    build_mapping_summary,
    build_processing_summary,
    group_review_rows,
)
from app.views.imports.mapping_palette import derive_mapping_palette_state


@dataclass
class ImportSessionState:
    entity_hint: str = ""
    filename: str = ""
    file_type: str = ""
    session_id: str = ""
    task_id: str = ""
    row_count: int = 0
    detected_entity: str = ""
    headers: list[str] = field(default_factory=list)
    detected_columns: list[dict[str, Any]] = field(default_factory=list)
    column_mapping: dict[str, str] = field(default_factory=dict)
    preview_rows: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    inference_summary: dict[str, Any] = field(default_factory=dict)
    bundle_mode: str = "single_entity"
    topology_side_hint: str = "unknown"
    file_model_hint: str = "unknown"
    dominant_side: str = "unknown"
    dominant_side_confidence: float = 0.0
    row_mixed_review_count: int = 0
    semantic_projection_conflicts: list[str] = field(default_factory=list)
    price_dialect_summary: dict[str, Any] = field(default_factory=dict)
    import_supported: bool = True
    blocking_code: str = ""
    blocking_message: str = ""
    entity_type_confidence: float = 0.0
    manual_mapping_required: bool = False
    manual_mapping_reasons: list[str] = field(default_factory=list)
    recoverability_summary: dict[str, int] = field(default_factory=dict)
    sheet_profiles: list[dict[str, Any]] = field(default_factory=list)
    column_semantic_profiles: list[dict[str, Any]] = field(default_factory=list)
    agency_profile_hints_used: dict[str, Any] = field(default_factory=dict)
    progress_detail: dict[str, Any] = field(default_factory=dict)
    execution_profile: str = ""
    queue_name: str = ""
    queue_position: int = 0
    agency_queue_depth: int = 0
    cancellation_state: str = ""
    queued_at: str = ""
    started_at: str = ""
    last_phase_started_at: str = ""
    last_phase_heartbeat_at: str = ""
    wait_state: str = ""
    wait_reason: str = ""
    wait_seconds: int = 0
    stalled: bool = False
    stalled_reason: str = ""
    can_cancel: bool = False
    can_close: bool = True
    mapping_palette_mode: str = "entity_only"
    available_mapping_fields: list[str] = field(default_factory=list)
    preview_entity_counts: dict[str, int] = field(default_factory=dict)
    preview_auto_fix_summary: dict[str, int] = field(default_factory=dict)
    preview_attention_summary: dict[str, int] = field(default_factory=dict)
    result_entity_counts: dict[str, int] = field(default_factory=dict)
    result_auto_fix_summary: dict[str, int] = field(default_factory=dict)
    result_attention_summary: dict[str, int] = field(default_factory=dict)
    experience_summary: ImportExperienceSummary | None = None
    review_groups: list[ImportReviewGroupRecord] = field(default_factory=list)
    review_page: ImportReviewPage | None = None
    review_pane_state: ImportReviewPaneState = field(default_factory=ImportReviewPaneState)

    # Progress
    progress: int = 0
    status: str = "idle"  # idle, uploading, mapping, running, completed, failed
    stage: str = ""
    review_count: int = 0
    review_pending_group_count: int = 0
    review_mode: str = "groups"
    review_state: str = "none"
    overflow_blocking: bool = False
    review_disabled: bool = False
    review_disabled_reason: str = ""
    review_overflow_count: int = 0
    review_total_count: int = 0
    review_rows: list[dict[str, Any]] = field(default_factory=list)
    error_message: str = ""

    # Final Result
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    result_zero_change: bool = False
    result_zero_change_reasons: list[str] = field(default_factory=list)
    terminal_reason: str = ""


class ImportWizardController(QObject):
    """
    Manages the state of the import wizard and communication with the API.
    """

    stateChanged = Signal()
    progressChanged = Signal(int)
    statusChanged = Signal(str)
    errorOccurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.state = ImportSessionState()

    def update_state(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
        self._refresh_derived_state()
        self.stateChanged.emit()

    def reset(self) -> None:
        self.state = ImportSessionState()
        self._refresh_derived_state()
        self.stateChanged.emit()

    def _refresh_derived_state(self) -> None:
        state = self.state
        valid_palette_modes = {"entity_only", "same_side_union", "recovery_union"}
        derived_mode, _candidate_entities = derive_mapping_palette_state(
            bundle_mode=state.bundle_mode,
            topology_side_hint=state.topology_side_hint,
            detected_entity=state.detected_entity or state.entity_hint,
            manual_mapping_required=bool(state.manual_mapping_required),
            detected_columns=list(state.detected_columns or []),
            column_mapping=dict(state.column_mapping or {}),
            sheet_profiles=list(state.sheet_profiles or []),
            selected_sheet_name=str(
                (
                    state.inference_summary.get("selected_sheet_name", "")
                    if isinstance(state.inference_summary, dict)
                    else ""
                )
                or ""
            ),
        )
        if state.mapping_palette_mode not in valid_palette_modes or (
            state.mapping_palette_mode == "entity_only" and derived_mode != "entity_only"
        ):
            state.mapping_palette_mode = derived_mode
        if state.mapping_palette_mode in {"same_side_union", "recovery_union"}:
            if str(state.topology_side_hint or "unknown") == "client_side":
                state.available_mapping_fields = [
                    "family_name",
                    "phone",
                    "remarks",
                    "is_vip",
                    "status",
                    "tags",
                    "action",
                    "type",
                    "wilaya",
                    "locations",
                    "budget_min",
                    "budget_max",
                    "surface_min",
                    "surface_max",
                    "beds_min",
                    "floor_min",
                    "floor_max",
                    "furnished",
                    "elevator",
                    "accessibility_required",
                ]
            else:
                state.available_mapping_fields = [
                    "family_name",
                    "phone",
                    "remarks",
                    "is_vip",
                    "status",
                    "action",
                    "type",
                    "wilaya",
                    "location",
                    "budget",
                    "surface",
                    "beds",
                    "floor",
                    "furnished",
                    "elevator",
                    "accessibility_supported",
                    "price_negotiable",
                    "price_flex_pct",
                    "link",
                    "latitude",
                    "longitude",
                ]
        else:
            state.available_mapping_fields = []
        if not state.review_groups and state.review_rows:
            state.review_groups = group_review_rows(list(state.review_rows or []))
        if state.review_groups:
            valid_group_keys = {group.group_key for group in state.review_groups}
            if state.review_pane_state.selected_group_key not in valid_group_keys:
                state.review_pane_state.selected_group_key = state.review_groups[0].group_key
        else:
            state.review_pane_state.selected_group_key = None
        if state.status in {"mapping", "execute_ready"}:
            state.experience_summary = build_mapping_summary(
                manual_mapping_required=bool(state.manual_mapping_required),
                import_supported=bool(state.import_supported),
                blocking_message=str(state.blocking_message or ""),
                preview_entity_counts=dict(state.preview_entity_counts or {}),
                preview_auto_fix_summary=dict(state.preview_auto_fix_summary or {}),
                row_count=int(state.row_count or 0),
            )
            return
        if state.status in {"uploading", "queued", "running", "ready"} or state.stage in {
            "upload",
            "executing",
            "review",
        }:
            state.experience_summary = build_processing_summary(
                status=str(state.status or ""),
                stage=str(state.stage or ""),
                row_count=int(state.row_count or 0),
                queue_position=int(state.queue_position or 0),
                agency_queue_depth=int(state.agency_queue_depth or 0),
                progress_detail=dict(state.progress_detail or {}),
                topology_side_hint=str(state.topology_side_hint or "unknown"),
            )
            return
        if state.status in {"completed", "failed"}:
            state.experience_summary = build_final_summary(
                status=str(state.status or ""),
                created_count=int(state.created_count or 0),
                updated_count=int(state.updated_count or 0),
                error_count=int(state.error_count or 0),
                skipped_count=int(state.skipped_count or 0),
                result_entity_counts=dict(state.result_entity_counts or {}),
                result_auto_fix_summary=dict(state.result_auto_fix_summary or {}),
                result_attention_summary=dict(state.result_attention_summary or {}),
                row_count=int(state.row_count or 0),
                result_zero_change=bool(state.result_zero_change),
                result_zero_change_reasons=list(state.result_zero_change_reasons or []),
                terminal_reason=str(state.terminal_reason or ""),
            )
            return
        state.experience_summary = None
