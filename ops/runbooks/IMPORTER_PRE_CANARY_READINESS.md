# Importer Pre-Canary Readiness

This checklist defines what must be true before importer canary starts.

## Contract Truth

The documented importer contract must match the code:

- public importer routes are documented
- grouped DB-backed review is documented as the current truth
- wait-state and cancel semantics are documented
- `mapping_palette_mode` and `recovery_union` are documented

## Tests That Must Pass

- `checks.ps1 -Stage pr`
- `checks.ps1 -Stage full`
- importer docs contract test
- importer truth matrix suite
- importer replay corpus suite
- importer execution health contract tests
- stalled repair contract tests

## Required Importer Docs

- `docs/architecture/IMPORTER_ARCHITECTURE.md`
- `docs/architecture/CONTROL_PLANE.md`
- `docs/guides/OPERATING_EXPENSIVE_WORK.md`
- `ops/runbooks/IMPORTER_OPERATIONS.md`
- `ops/runbooks/OBSERVABILITY_RUNBOOK.md`
- `docs/reference/REPO_STATE.md`
- `ops/policies/BACKEND_RISK_REGISTER.md`

## Observability Checks

Before canary, confirm importer telemetry includes:

- `terminal_reason`
- `wait_state`
- `stalled_reason`
- `mapping_palette_mode`
- `manual_mapping_required`
- `result_zero_change`
- `cancel_requested`
- `repair_attempted`
- `requeued_after_lease_expiry`

## Watchdog and Queue Checks

Confirm all of these are true:

- `repair_stalled_import_jobs_task` is scheduled
- `requeue_expired_import_phases_task` is scheduled
- queued jobs do not stall indefinitely without diagnostics
- repeated stale-start jobs fail diagnostically instead of hanging forever

## Minimum Replay Corpus

Minimum replay corpus before canary:

- at least `20` fixture files
- includes weak listing+offer recovery
- includes weak client+demande recovery
- includes zero-change
- includes review-required
- includes blocked cases
- includes waiting-for-worker diagnostic coverage
- includes cancelled contract coverage

## Minimum Truth Matrix

Minimum truth matrix before canary:

- at least `60` explicit cases
- includes weak same-side rows
- includes cross-side contamination
- includes `recovery_union` palette cases
- includes `entity_only` palette cases
- includes `same_side_union` palette cases

## Manual Smoke Matrix

Each row below must be covered by either an automated test or a named manual
smoke.

### Manual smoke 1: client-side bundle import

1. Start local stack and worker services.
2. Import a `client + demande` file.
3. Confirm preview shape, execution, summary, and visible client rows.

### Manual smoke 2: listing-side bundle import

1. Import a `listing + offer` file.
2. Confirm preview shape, execution, summary, and visible property rows.

### Manual smoke 3: weak recovery-union mapping

1. Import a weak same-side bundle file.
2. Confirm `mapping_palette_mode = recovery_union`.
3. Confirm extra root/child fields are available.
4. Confirm preview re-evaluates after manual mapping.

### Manual smoke 4: zero-change case

1. Import a duplicate-heavy or no-op fixture.
2. Confirm warning summary and `terminal_reason = zero_change`.

### Manual smoke 5: queued or waiting-for-worker case

1. Saturate the same-agency importer slot.
2. Start another import.
3. Confirm `wait_state` is truthful and the user is not trapped.

### Manual smoke 6: cancel case

1. Start a queued or waiting import.
2. Use cancel from the wizard.
3. Confirm `terminal_reason = cancelled`.

## Final Scan Matrix

The finish gate is not complete unless the scan matrix covers:

- clients happy path
- listings happy path
- waiting-for-worker path
- queued path
- listing mapping recovery
- client mapping recovery
- zero-change path
- grouped review path
- offline child-fetch path
- distributed chaos path

## Explicit Non-Go Criteria

Do not start canary if any are true:

- importer docs still describe obsolete review storage as authoritative
- replay coverage is still seed-only and misses recovery cases
- stalled repair has no deterministic contract tests
- operators cannot distinguish zero-change, review-required, cancelled, and failed imports from documented fields
- manual smoke steps depend on undocumented tribal knowledge
