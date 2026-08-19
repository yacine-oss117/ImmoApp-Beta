# Operating Expensive Work

This is the operator quick guide for the importer and match rebuild control
plane.

## First Questions

When the system feels slow, answer these in order:

1. Is the runtime profile `green`, `yellow`, or `red`?
2. Is admission `normal` or `degraded`?
3. Is the pressure coming from imports or match rebuilds?
4. Are importer jobs `queued`, `waiting_for_worker`, `running`, `review`, or
   terminal?

## Importer States

- `queued`
  - waiting behind another import for the same agency
- `waiting_for_worker`
  - accepted into execution, but no worker phase has started yet
- `running`
  - active execution is in progress
- `review`
  - grouped operator review is pending
- `completed`
  - terminal finish, including `success` and `zero_change`
- `failed`
  - terminal failure, `cancelled`, or `emergency_overflow`

Useful status fields:

- `execution_profile`
- `admission_mode`
- `pressure_reason`
- `queue_position`
- `agency_queue_depth`
- `wait_state`
- `wait_reason`
- `wait_seconds`
- `stalled`
- `stalled_reason`
- `cancellation_state`
- `mapping_palette_mode`
- `terminal_reason`

Important rule:

- `waiting_for_worker` is not automatically broken
- it means the job is accepted but not yet picked up
- only `stalled = true` changes it into an operator concern

## Importer Outcome Language

Current terminal outcome language:

- `success`
- `zero_change`
- `review_required`
- `failed`
- `cancelled`
- `emergency_overflow`

Interpret them like this:

- `zero_change`
  - the file was processed, but nothing new was added or updated
- `review_required`
  - the import is not done; grouped review still owns the next step
- `cancelled`
  - operator or user stopped the import
- `failed`
  - terminal failure without a safe completion

## Mapping Recovery Signals

When a file is messy, inspect:

- `manual_mapping_required`
- `manual_mapping_reasons`
- `mapping_palette_mode`
- `recoverability_summary`
- `sheet_profiles`
- `column_semantic_profiles`
- `agency_profile_hints_used`

`mapping_palette_mode` meanings:

- `entity_only`
  - only one entity catalog is exposed
- `same_side_union`
  - strong same-side bundle, root + child fields are both available
- `recovery_union`
  - weak same-side file, extra root + child field choices are available so the
    operator can guide recovery safely

## Health Snapshot

Admin `health/snapshot/` should be the first place you look.

Important payload sections:

- `import_runtime_health`
- `import_runtime_cleanup`
- `import_learning_health`
- `match_rebuild_health`
- `tenant_budget_state`
- `match_runtime_profile`
- `match_runtime_profile_reason`

## Janitors

The repair paths are intentional:

- import phase lease repair
- importer/review task-attempt fencing
- stalled importer repair
- importer temp/artifact cleanup
- match rebuild janitor

If stale work clears after a short delay, that is usually a janitor/repair
path, not magic.
