# Importer Architecture

This document describes the importer as it exists in the repo now.

## What It Owns

The importer owns file ingestion for:

- `client`
- `demande`
- `listing`
- `offer`

Its responsibilities are:

- secure upload and staged file retrieval
- parse and sheet/workbook inspection
- column semantics and file-shape inference
- dominant-side file-model classification for chaotic sheets
- preview and manual mapping diagnostics
- same-side bundle recovery
- review generation and grouped DB-backed review
- distributed prepare/plan/load/finalize execution
- queueing, cancellation, wait-state diagnostics, and notifications

It does not own business storage itself. Upload bytes are staged through the
storage service and then pulled back into the importer parse path.

## Public API Surface

Canonical importer routes:

- `POST /api/v1/import/upload/`
- `POST /api/v1/import/presign/`
- `POST /api/v1/import/complete/`
- `POST /api/v1/import/preview/`
- `POST /api/v1/import/execute/`
- `POST /api/v1/import/<session_id>/cancel/`
- `GET /api/v1/import/status/<task_id>/`
- `GET /api/v1/import/<session_id>/review/`
- `POST /api/v1/import/<session_id>/review/submit/`

Readiness semantics on `POST /api/v1/import/presign/` are explicit:

- `503` with `IMPORT_SERVICE_WARMING_UP` or `IMPORT_STORAGE_NOT_READY`
- retryable readiness responses are transport/storage outcomes, not parse errors

Route/view owners:

- `server/api/views_import_upload.py`
- `server/api/views_import_preview.py`
- `server/api/views_import_execute.py`
- `server/api/views_import_review.py`

Task/maintenance owners:

- `server/api/tasks_import.py`
- `server/api/tasks_maintenance.py`

Persistent job/review state:

- `server/imports/models.py`
  - `ImportJob`
  - `ImportWorkflowState`
  - `ImportReviewGroup`
  - `ImportReviewItem`
  - `ImportRowAudit`

## Authoritative Owner Files

If helper docs or compatibility surfaces disagree with these files, these
files win:

- route contract:
  - `server/api/views_import_upload.py`
  - `server/api/views_import_preview.py`
  - `server/api/views_import_execute.py`
  - `server/api/views_import_review.py`
- background execution:
  - `server/api/tasks_import.py`
- workflow authority:
  - `server/services/import_chunk_workflow.py`
- queue and dispatch:
  - `server/services/import_job_queue.py`
- execution health and stuck-state diagnosis:
  - `server/services/import_execution_health.py`
- normalized preview/execute decision engine:
  - `server/services/import_decision.py`
- mapping recovery palette:
  - `server/services/import_mapping_palette.py`
- pipeline trace snapshots:
  - `server/services/import_trace_snapshot.py`
- phase owners:
  - `server/services/import_prepare_service.py`
  - `server/services/import_planning_service.py`
  - `server/services/import_load_service.py`
  - `server/services/import_finalize_service.py`
- review API and backend:
  - `server/api/views_import_review.py`
  - `server/services/import_review_store.py`
  - `server/services/import_review_db_state.py`
  - `server/services/import_review_execution_service.py`
  - `server/services/import_review_queries.py`
  - `server/services/import_review_mutations.py`
  - `server/services/import_review_payloads.py`
  - `server/services/import_review_resolution.py`
  - `server/services/import_review_grouping.py`
  - `server/services/import_review_policy.py`
  - `server/services/import_review_rescue.py`

## Execution Ownership Map

The importer execution surface is intentionally split by ownership.

HTTP edge:

- `server/api/views_import_execute.py`
  - request auth/validation and `Response(...)`

Execute/status/cancel helpers:

- `server/services/import_execute_request.py`
  - execute admission, enqueue/start decisions, and response shaping
- `server/services/import_status_payload.py`
  - importer status payload shaping and queue-depth projection
- `server/services/import_cancel_flow.py`
  - cancel mechanics and cancel response shaping

Direct execution owners:

- `server/services/import_executor.py`
  - direct execution orchestration and phase wiring
- `server/services/import_execution_state.py`
  - direct execution state persistence, failure projection, and cleanup helpers
- `server/services/import_executor_checkpoint.py`
  - planned-artifact checkpoint fingerprint/load/persist/restore/clear helpers

Distributed workflow owners:

- `server/services/import_chunk_workflow.py`
  - stable workflow facade and compatibility seam
- `server/services/import_workflow_storage.py`
  - workflow payload/state persistence
- `server/services/import_workflow_manifests.py`
  - manifest persistence, staging, and row/materialization helpers
- `server/services/import_workflow_leases.py`
  - phase lease lifecycle and cancellation requests
- `server/services/task_attempt_lifecycle.py`
  - domain-neutral task-attempt transition rules and monotonic terminal
    decisions
- `server/services/import_review_submit_attempts.py`
  - workflow-backed review-submit attempt persistence, row-locked
    cancellation, and terminal fencing
- `server/services/import_phase_attempts.py`
  - distributed phase attempt mapping over the existing
    `ImportChunkPhase` lease contract
- `server/services/import_workflow_dispatch.py`
  - workflow progress rollup and phase dispatch advancement

Phase owners:

- prepare public facade:
  - `server/services/import_prepare_service.py`
- prepare mode-specific flows:
  - `server/services/import_prepare_single_flow.py`
  - `server/services/import_prepare_child_flow.py`
  - `server/services/import_prepare_bundle_flow.py`
- planning public facade:
  - `server/services/import_planning_service.py`
- planning mode-specific flows:
  - `server/services/import_plan_single_flow.py`
  - `server/services/import_plan_child_flow.py`
  - `server/services/import_plan_bundle_flow.py`
- load owners:
  - `server/services/import_load_service.py`
  - `server/services/import_distributed_execution.py`
  - `server/services/import_load_policy.py`
- finalize owner:
  - `server/services/import_finalize_service.py`

Review owners:

- review API/view edge:
  - `server/api/views_import_review.py`
- review storage/public facade:
  - `server/services/import_review_store.py`
- review DB-backed persistence, compatibility sampling, and legacy backfill:
  - `server/services/import_review_db_state.py`
- review read/query helpers:
  - `server/services/import_review_queries.py`
- review stored resolution-state mutation helpers:
  - `server/services/import_review_mutations.py`
- review payload shaping and submit normalization:
  - `server/services/import_review_payloads.py`
- review execution/public facade:
  - `server/services/import_review_execution_service.py`
- review resolution execution internals:
  - `server/services/import_review_resolution.py`
- review grouping/policy/rescue domain helpers:
  - `server/services/import_review_grouping.py`
  - `server/services/import_review_policy.py`
  - `server/services/import_review_rescue.py`

## Desktop Client Surface

Main UI owner:

- `app/views/imports/wizard_dialog.py`

Wizard state:

- `app/views/imports/wizard_state.py`
  - `ImportSessionState`

Step widgets:

- `app/views/imports/step_upload.py`
- `app/views/imports/step_mapping.py`
- `app/views/imports/step_execution.py`
- `app/views/imports/step_review.py`
- `app/views/imports/step_summary.py`

Review-step split owners:

- stable review-step root:
  - `app/views/imports/step_review.py`
- row-card widget/editor:
  - `app/views/imports/review_row_card.py`
- page hydration, conflict mapping, and refresh helpers:
  - `app/views/imports/review_page_controller.py`
- review GET/submit transport adapter:
  - `app/views/imports/review_api_adapter.py`
- pure action and hidden-draft shaping:
  - `app/views/imports/review_actions.py`

The desktop importer is a wizard client. It does not parse or resolve business
identity locally. It uploads, previews, polls status, renders grouped review,
submits operator decisions, and shows final outcomes.

## Core Pipeline

Shared importer logic:

- `core/importer/detection/`
- `core/importer/normalizers/`
- `core/importer/parsers/`
- `core/importer/validation/`
- `core/importer/intelligence/`
- `core/importer/normalize_pipeline.py`
- `core/importer/security.py`

Server orchestration:

- `server/services/import_mapping.py`
- `server/services/import_decision.py`
- `server/services/import_mapping_gate.py`
- `server/services/import_mapping_palette.py`
- `server/services/import_type_inference.py`
- `server/services/import_recovery.py`
- `server/services/import_recoverability.py`
- `server/services/import_column_semantics.py`
- `server/services/import_sheet_intelligence.py`
- `server/services/import_agency_profile.py`
- `server/services/import_review_policy.py`
- `server/services/import_executor.py`
- `server/services/import_execution_state.py`
- `server/services/import_executor_checkpoint.py`
- `server/services/import_execute_request.py`
- `server/services/import_cancel_flow.py`
- `server/services/import_status_payload.py`
- `server/services/import_workflow_storage.py`
- `server/services/import_workflow_manifests.py`
- `server/services/import_workflow_leases.py`
- `server/services/import_workflow_dispatch.py`
- `server/services/import_prepare_single_flow.py`
- `server/services/import_prepare_child_flow.py`
- `server/services/import_prepare_bundle_flow.py`
- `server/services/import_plan_single_flow.py`
- `server/services/import_plan_child_flow.py`
- `server/services/import_plan_bundle_flow.py`
- `server/services/import_notifications.py`

Normalization guarantees:

- extracted extras from normalizers are merged deterministically
- equivalent duplicate extras are accepted once
- conflicting extra values do not silently overwrite each other
- conflicting extras force review and stay out of normalized business data
- numeric parsing is field-aware:
  - measurement fields accept measurement units like `m²`
  - quantity fields accept quantity suffixes like `room` or `étage`
- Algerian real-estate forms are handled explicitly:
  - `1.5 milliard`
  - `1 milliard 500`
  - `5 millions/mois`
  - `80-120`
  - `environ 90`
  - `RDC`
  - `Entre 2 et 4`
- canonical stored money stays DZD-scale:
  - explicit `DZD` / `DA` text wins
  - explicit `centime` / `cts` text wins
  - colloquial `mrd` / `milliard` defaults to local centime-billion speech
  - bare `m` / `M` / `million` forms stay review-only unless header, column, or
    agency context makes the scale provable
  - bare decimals like `1.5` no longer collapse to `15`
- ambiguous shorthand such as `15000 u` stays review-only instead of silently
  coercing to a numeric value
- review rows now carry explicit price interpretation candidates so operators
  can confirm DZD vs local centime-style shorthand without reading logs
- Algerian service/special phone ranges like `08...` and `09...` are accepted as
  valid phone kinds instead of being treated as unknown prefixes
- passthrough sanitization failures quarantine the normalized value to `None`
  and force review instead of silently keeping unsafe raw text in normalized
  business data
- parse-time semantic inference is non-lossy:
  - `SemanticEvidenceRow` keeps every semantic cell independently
  - duplicate semantic domains are surfaced as
    `semantic_projection_conflicts`
  - file-model diagnostics now include:
    - `file_model_hint`
    - `dominant_side`
    - `dominant_side_confidence`
    - `row_mixed_review_count`

## Runtime Lifecycle

### 1. Upload

There are two upload paths:

- direct API upload through `import/upload/`
- presigned object-storage upload through `import/presign/` and `import/complete/`

For local secure desktop mode, `import/presign/` is allowed to return retryable
storage/readiness `503` responses instead of pretending the file is unreadable.

Both end in a persisted `ImportJob`.

### 2. Parse

`server/api/tasks_import.py:import_parse_task` performs parse and file-shape
inference. It stores:

- detected columns
- preview sample rows
- `final_inference`
- workbook/sheet profiles
- column semantic profiles
- agency profile hints used
- manual mapping gate diagnostics
- price dialect profiles and preview summary

Important rule:

- UI entity hint is only a hint
- content inference remains authoritative

### 3. Preview and Manual Mapping

`import/preview/` exposes:

- preview rows
- entity and topology hints
- `manual_mapping_required`
- `manual_mapping_reasons`
- `mapping_palette_mode`
- `mapping_palette_reason`
- `mapping_candidate_entities`
- `recoverability_summary`
- `sheet_profiles`
- `column_semantic_profiles`
- `agency_profile_hints_used`

`mapping_palette_mode` is canonical and has three modes:

- `entity_only`
  - only the inferred entity fields are shown
- `same_side_union`
  - explicit root + child field union for strong same-side bundles
- `recovery_union`
  - weak same-side bundle recovery mode for files that may contain both
    `client + demande` or `listing + offer`

Manual recovery behavior:

- weak same-side bundle files do not have to be blocked immediately
- the preview can expose `recovery_union`
- the user can map additional root/child fields
- preview can then re-evaluate the file more safely

Normalized internal decision contract:

- `ImportDecision = { outcome, confidence, detected_entity, topology_side_hint, bundle_mode, mapping_palette_mode, reason_codes, recoverability_summary }`

Current rule:

- preview writes the current `ImportDecision` snapshot into job inference state
- execute recomputes the decision from the user’s latest mapping instead of trusting stale preview flags
- explicit same-side recovery mappings can clear a stale manual-mapping requirement when the mapped root + child fields are now coherent

### 4. Review

Grouped DB-backed review is the current truth.

Authoritative review models:

- `ImportReviewGroup`
- `ImportReviewItem`

Authoritative review backend owners:

- `server/services/import_review_store.py`
- `server/services/import_review_db_state.py`
- `server/services/import_review_grouping.py`
- `server/services/import_review_queries.py`
- `server/services/import_review_mutations.py`
- `server/services/import_review_payloads.py`
- `server/services/import_review_execution_service.py`
- `server/services/import_review_resolution.py`

Authoritative review UI owners:

- `app/views/imports/step_review.py`
- `app/views/imports/review_row_card.py`
- `app/views/imports/review_page_controller.py`
- `app/views/imports/review_api_adapter.py`
- `app/views/imports/review_actions.py`

Compatibility note:

- `ImportJob.review_rows` still exists as a compatibility sample surface
- it is not the authoritative review model

Review payloads can include:

- normalized row payload
- raw/original row payload
- issue group and issue summary
- candidate matches
- inline review fields
- recoverability and blocking reasons
- bulk-fix groups
- grouped resolution metadata

### 5. Execute

`import/execute/` schedules distributed execution and background phases.

Execution bundle modes:

- `single_entity`
- `same_side_bundle`
- `mixed_blocked`

Phase ownership:

- execute/status/cancel HTTP edge
  - `server/api/views_import_execute.py`
- execute admission and response shaping
  - `server/services/import_execute_request.py`
- status payload shaping
  - `server/services/import_status_payload.py`
- cancel mechanics
  - `server/services/import_cancel_flow.py`
- direct execution orchestration
  - `server/services/import_executor.py`
- direct execution state/failure/cleanup
  - `server/services/import_execution_state.py`
- direct execution checkpoint helpers
  - `server/services/import_executor_checkpoint.py`
- prepare
  - `server/services/import_prepare_service.py`
  - mode-specific implementations under `server/services/import_prepare_*_flow.py`
- plan
  - `server/services/import_planning_service.py`
  - mode-specific implementations under `server/services/import_plan_*_flow.py`
- load
  - `server/services/import_load_service.py`
  - distributed phase entry in `server/services/import_distributed_execution.py`
  - shared load policy in `server/services/import_load_policy.py`
- finalize
  - `server/services/import_finalize_service.py`

Workflow authority:

- `server/services/import_chunk_workflow.py`
  - facade over:
    - `server/services/import_workflow_storage.py`
    - `server/services/import_workflow_manifests.py`
    - `server/services/import_workflow_leases.py`
    - `server/services/import_workflow_dispatch.py`

Queue/dispatch authority:

- `server/services/import_job_queue.py`

### 6. Status, Wait States, and Cancellation

`GET /api/v1/import/status/<task_id>/` is the canonical public status contract.

Important fields:

- `status`
- `stage`
- `progress`
- `wait_state`
- `wait_reason`
- `wait_seconds`
- `stalled`
- `stalled_reason`
- `can_cancel`
- `can_close`
- `cancellation_state`
- `mapping_palette_mode`
- `result_zero_change`
- `result_zero_change_reasons`
- `terminal_reason`

Execution-step states are:

- `queued`
- `waiting_for_worker`
- `running`
- `review`
- `completed`
- `failed`

Meaning of `waiting_for_worker`:

- the import was accepted
- the job is effectively waiting for a worker pickup or stale-start repair
- it is not the same thing as active phase execution

Cancellation route:

- `POST /api/v1/import/<session_id>/cancel/`

Cancellation/status owner split:

- `server/api/views_import_execute.py`
  - request auth/validation and `Response(...)`
- `server/services/import_status_payload.py`
  - status payload shaping
- `server/services/import_cancel_flow.py`
  - cancel mechanics

Cancellation semantics:

- queued jobs can be cancelled immediately
- active distributed work becomes `cancel_requested` and running phase attempts
  are fenced by the current phase lease token
- review-submit workers use a workflow-backed task-attempt fence; stale workers
  are ignored, and started-worker repair first invalidates the attempt before
  returning the job to review-ready state
- cancellation is best-effort and does not roll back already committed rows
- matcher/cache worker fencing is separate and intentionally out of scope here

### 7. Terminal Outcomes

Canonical terminal outcomes:

- `success`
- `zero_change`
- `review_required`
- `failed`
- `cancelled`
- `emergency_overflow`

Interpretation:

- `zero_change`
  - import finished cleanly, but nothing changed
- `review_required`
  - operator review is still pending
- `emergency_overflow`
  - unresolved review volume exceeded the safe bound

## Control-Plane and Watchdog Model

The importer uses:

- agency-scoped execution queueing
- workflow payload persistence in DB
- lease-based chunk phases
- scheduled maintenance repair for expired phases and stalled jobs

Key control-plane helpers:

- `server/services/import_job_queue.py`
- `server/services/import_execution_health.py`
- `server/api/tasks_maintenance.py`

## Testing and Anti-Regression Strategy

The importer no longer relies only on ad hoc screenshots or single bugfix
tests.

Canonical anti-regression surfaces:

- truth matrix:
  - `app/tests/fixtures/import_truth/row_truth_matrix.json`
  - `app/tests/server_tests/test_import_truth_matrix.py`
- replay corpus:
  - `app/tests/fixtures/import_corpus/`
  - `app/tests/server_tests/test_import_corpus_replay.py`
- pipeline trace harness:
  - `app/tests/fixtures/import_pipeline_trace/`
  - `app/tests/server_tests/test_import_pipeline_trace_matrix.py`
- execution health and cancel contract tests:
  - `app/tests/server_tests/test_import_execution_health_contract.py`
  - `app/tests/server_tests/test_import_cancel_contract.py`

The design intent is:

- clean files import cleanly
- ugly files review or block safely
- weak same-side files can use `recovery_union`
- stuck execution paths surface explicit wait/cancel/close semantics
