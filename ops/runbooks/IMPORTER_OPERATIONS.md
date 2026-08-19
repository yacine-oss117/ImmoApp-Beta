# Importer Operations

## What To Check First

1. `health/snapshot/`
2. importer status payload
3. `import_runtime_health`
4. `import_runtime_cleanup`
5. workflow payload and latest chunk phases

## Where Each Concern Lives

Use this map before diving into logs:

- execute/status/cancel HTTP edge:
  `server/api/views_import_execute.py`
- execute admission and response shaping:
  `server/services/import_execute_request.py`
- status payload projection:
  `server/services/import_status_payload.py`
- cancel mechanics:
  `server/services/import_cancel_flow.py`
- direct execution and checkpoint restore:
  `server/services/import_executor.py`
  `server/services/import_execution_state.py`
  `server/services/import_executor_checkpoint.py`
- distributed workflow facade:
  `server/services/import_chunk_workflow.py`
- workflow payload/manifests/leases/dispatch owners:
  `server/services/import_workflow_storage.py`
  `server/services/import_workflow_manifests.py`
  `server/services/import_workflow_leases.py`
  `server/services/import_workflow_dispatch.py`
- review API/backend owners:
  `server/api/views_import_review.py`
  `server/services/import_review_store.py`
  `server/services/import_review_execution_service.py`
  `server/services/import_review_queries.py`
  `server/services/import_review_mutations.py`
  `server/services/import_review_payloads.py`
  `server/services/import_review_resolution.py`
- review desktop owners:
  `app/views/imports/step_review.py`
  `app/views/imports/review_row_card.py`
  `app/views/imports/review_page_controller.py`
  `app/views/imports/review_api_adapter.py`
  `app/views/imports/review_actions.py`
- prepare and planning public facades:
  `server/services/import_prepare_service.py`
  `server/services/import_planning_service.py`
- mode-specific prepare and planning logic:
  `server/services/import_prepare_*_flow.py`
  `server/services/import_plan_*_flow.py`

## First Triage Fields

Always capture these first:

- `wait_state`
- `wait_reason`
- `wait_seconds`
- `stalled`
- `stalled_reason`
- `can_cancel`
- `mapping_palette_mode`
- `file_model_hint`
- `dominant_side`
- `semantic_projection_conflicts`
- `manual_mapping_required`
- `decision_outcome`
- `decision_reason_codes`
- `review_state`
- `terminal_reason`

## Bad Signs

- many queued imports for one agency
- many jobs stuck in `waiting_for_worker`
- repeated `stalled_reason = worker_not_picked_up`
- repeated `stalled_reason = phase_heartbeat_expired`
- repeated `requeued_after_lease_expiry`
- manual-mapping-required imports growing unexpectedly
- zero-change imports growing unexpectedly for one agency
- shadow aliases never promoting for agencies with repeated corrections

## Safe Actions

- rerun importer janitors
- inspect queue depth
- inspect worker-import logs
- inspect workflow payload repair metadata
- inspect the specific owner module for the failing concern instead of starting
  in `import_chunk_workflow.py` by default
- inspect `inference_summary.import_decision`
- inspect whether the runtime profile is pinned to `red`
- verify object storage is reachable
- inspect `import_learning_health`
- inspect `sheet_profiles` and `column_semantic_profiles`
- inspect `file_model_hint`, `dominant_side`, and projection-conflict diagnostics
- inspect grouped review counts

## Unsafe Actions

- do not manually delete workflow rows before cleaning artifacts
- do not force a second running import for the same agency
- do not treat `review` as a system failure
- do not assume `waiting_for_worker` means active phase execution

## Cancel Rules

Safe actions:

- safe to cancel queued imports
- safe to request cancel for active running work

Unsafe actions:

- unsafe to force duplicate same-agency running imports
- unsafe to assume cancel rolls back committed rows

## Operator Responses

### Queued too long

1. Inspect `queue_position` and `agency_queue_depth`.
2. Confirm whether another same-agency import is still running.
3. If not, inspect `repair_stalled_import_jobs_task` output and re-run it.

### Waiting-for-worker too long

1. Confirm `wait_state = waiting_for_worker`.
2. Check `stalled_reason`.
3. Inspect workflow repair metadata:
   - `repair_attempted`
   - `repair_attempt_count`
   - `repair_last_reason`
4. If the job already exhausted one repair attempt, allow the watchdog to fail
   it diagnostically instead of forcing duplicate execution.

### Stale running phase

1. Confirm `stalled_reason = phase_heartbeat_expired`.
2. Inspect chunk phase lease fields and workflow cancellation state.
3. Run `requeue_expired_import_phases_task`.
4. Do not manually mutate phases that still hold a valid lease.

### Zero-change import

1. Confirm `terminal_reason = zero_change`.
2. Inspect `result_zero_change_reasons`.
3. Treat it as a warning outcome, not a crash.
4. Check whether the file was duplicate-heavy or review-heavy.

### Cancelled import

1. Confirm `terminal_reason = cancelled`.
2. Confirm `cancellation_state`.
3. Remember cancellation is best-effort and not a rollback of committed rows.

### Recovery-union mapping case

1. Confirm `mapping_palette_mode = recovery_union`.
2. Verify the file is a weak same-side bundle candidate, not mixed-side
   contamination.
3. Check `decision_outcome` and `decision_reason_codes`.
4. Let the operator map the additional child/root fields instead of forcing a
   flat import.
5. Re-run preview; if the latest mapped root + child fields are coherent, the
   stale manual-mapping requirement should clear automatically.

### Presign or upload readiness timeout

1. Distinguish readiness from parse failure.
2. If `import/presign/` returned `503`, inspect the response code:
   - `IMPORT_SERVICE_WARMING_UP`
   - `IMPORT_STORAGE_NOT_READY`
3. Treat these as local service/storage readiness issues, not bad-file issues.
4. Verify object storage reachability and retry after the advertised delay.

## Chaotic Lead Sheets

For noisy agency lead sheets, preview can classify the file as:

- `client_lead_sheet`
- `listing_inventory`
- `mixed`
- `unknown`

Operator meaning:

- `client_lead_sheet`: treat root columns as client identity and the weaker
  property columns as demande preferences
- `listing_inventory`: treat owner/property root columns and offer details as
  one same-side inventory file
- `mixed`: do not force one side; split or review

## Review Model Truth

Grouped DB-backed review is the current truth:

- `ImportReviewGroup`
- `ImportReviewItem`

Compatibility row blobs can still exist on `ImportJob`, but they are not the
authoritative review model.
