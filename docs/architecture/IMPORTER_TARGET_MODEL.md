# Importer Target Model

This document describes the recommended target model for finishing importer
hardening and reducing the remaining ETL risks.

It is intentionally forward-looking. If this document conflicts with
`docs/architecture/IMPORTER_ARCHITECTURE.md`, the current-state architecture
doc remains the source of truth for how the repo behaves today.

## Goal

The target importer should be:

- deterministic
- conservative
- replay-driven
- explainable
- recoverable
- observable

In plain terms:

- clean files should import automatically
- supported but messy files should be recoverable through mapping or review
- unsafe files should be blocked instead of silently guessed
- every important non-success state should clearly explain what happened and
  what the user can do next

## Recommended Model

Use a hybrid model:

- deterministic schema-aware parsing at the core
- heuristic evidence only where it improves recovery or UX
- confidence gates before any automatic import
- manual mapping as an explicit recovery path
- grouped review for unresolved but still supported cases
- block when the file shape is unsafe
- capture every real surprise as a replay fixture

This is better than a strict-schema-only model because agency files are often
messy. It is better than a heuristic-first model because silent coercion is
too risky.

## Allowed Outcomes

After parse, inference, and preview, the importer should always choose exactly
one of these outcomes:

1. `auto_import`
2. `manual_mapping`
3. `review`
4. `block`

No hidden fallback path should silently convert one of these outcomes into
another.

## Core Principles

### Deterministic

The same file, mapping, and settings should lead to the same importer
decision every time.

### Conservative

Low-confidence mixed or contaminated shapes should go to review or block,
never silent auto-load.

### Explainable

Every downgrade should carry explicit reason codes. The UI should explain:

- what happened
- why it happened
- what to do next

### Recoverable

If a file is supported but weak, manual mapping should expose enough fields to
recover it safely.

### Monotonic

Queue, worker, and finalize state must never move backward because of stale
workers or delayed updates.

### Replay-Driven

Every production anomaly should become:

- one replay fixture or truth-matrix case
- one regression test
- one explicit reason code if needed

### Observable

Operators should be able to distinguish quickly between:

- queued
- waiting for worker
- running
- review required
- zero change
- cancelled
- failed

## Target Importer Stack

The target importer architecture should have these layers:

1. schema-aware parser
2. evidence extractor
3. topology classifier
4. confidence gate
5. recovery mapping layer
6. grouped review layer
7. idempotent execution engine
8. trace and replay layer
9. observability and repair layer

## Decision Model

### 1. Parse

The parser extracts:

- workbook and sheet structure
- headers and aliases
- raw row shapes
- sample values

### 2. Extract evidence

The importer collects evidence such as:

- root identity strength
- child identity strength
- same-side bundle signals
- cross-side contamination
- weak or partial rows
- workbook conflict signals

### 3. Classify topology

The importer decides whether the file is:

- single entity
- same-side bundle
- child-only unsupported
- mixed-side unsafe
- workbook-conflicted

### 4. Confidence gate

Use confidence to choose:

- safe auto-import
- recovery mapping
- grouped review
- hard block

### 5. Recover if supported

If the file is supported but weak:

- expose union mapping palettes for same-side bundle recovery
- allow explicit user mapping to override weak inference
- rerun preview using the actual mapped field set

### 6. Review when unresolved

If rows are still unresolved but supportable:

- group review rows by issue type
- preserve issue reasons
- keep summary and status aligned with review state

### 7. Execute safely

Execution should be:

- idempotent
- monotonic
- repairable when safe
- terminally explicit when not repairable

## Best-Fit UX Model

### Preview

Preview should answer:

- what we found
- what is ready
- what needs mapping
- what would be blocked

### Mapping

Mapping should be a real recovery tool, not a dead end.

The UI should:

- hide technical labels
- expose same-side union fields when recovery is plausible
- only block continue when execute would actually reject

### Execution

Execution should never trap the user.

Users should always be able to:

- close for now
- cancel when allowed
- understand whether the job is queued, waiting for a worker, running, or
  stalled

### Summary

Summary should distinguish clearly between:

- success
- zero change
- review required
- cancelled
- failed

## Matching Implications

Matching should stay transparent for imported offers and demandes.

Important rule:

- import fields that affect matching should be visible in a user-friendly way

Examples:

- action
- property type
- location
- budget ranges
- size ranges
- negotiation margin

Match results should explain key reasons for a match instead of only showing a
score.

## Risk Strategy

The remaining ETL risk is mostly in ugly real-world files and operational edge
states, not in the normal happy path.

The best strategy is:

1. expand truth-matrix coverage
2. expand replay corpus coverage
3. improve explainability
4. strengthen repair and observability
5. run canary with anomaly capture

## Phase Plan

### Phase 1 - Truth Surface

Expand the truth matrix and replay corpus so the importer behavior is
explicitly defined for:

- clean files
- weak same-side bundles
- ugly but recoverable rows
- review-only rows
- blocked rows
- queue and wait-state diagnostics

### Phase 2 - Explainability

Make preview, mapping, review, execution, summary, and match UI tell one
consistent story using user language.

### Phase 3 - Operational Resilience

Strengthen:

- stalled-job repair
- stale-worker rejection
- repair metadata
- importer-specific metrics and logs

### Phase 4 - Final Gate

Before canary:

- fast lane green
- full lane green
- replay corpus expanded
- truth matrix expanded
- manual smoke pack written
- operator docs aligned

## Roadmap by Code Area

### Parser and classification

- `server/services/import_type_inference.py`
- `server/services/import_mapping_gate.py`
- `server/services/import_mapping_palette.py`
- `server/api/views_import_preview.py`

### Execution and repair

- `server/services/import_execute_request.py`
- `server/services/import_cancel_flow.py`
- `server/services/import_status_payload.py`
- `server/services/import_executor.py`
- `server/services/import_execution_state.py`
- `server/services/import_executor_checkpoint.py`
- `server/services/import_execution_health.py`
- `server/api/tasks_maintenance.py`
- `server/services/import_chunk_workflow.py`
- `server/services/import_workflow_*.py`
- `server/services/import_finalize_service.py`
- `server/api/views_import_execute.py`

### Wizard and UX

- `app/views/imports/step_upload.py`
- `app/views/imports/step_mapping.py`
- `app/views/imports/step_execution.py`
- `app/views/imports/step_review.py`
- `app/views/imports/step_summary.py`
- `app/views/imports/import_experience.py`
- `app/views/match_results_table_builder.py`

### Replay, tests, and docs

- `app/tests/fixtures/import_truth/row_truth_matrix.json`
- `app/tests/server_tests/test_import_corpus_replay.py`
- `app/tests/server_tests/test_import_pipeline_trace_matrix.py`
- `ops/runbooks/IMPORTER_PRE_CANARY_READINESS.md`
- `ops/runbooks/IMPORTER_OPERATIONS.md`

## What "Done" Looks Like

The importer is done enough for canary when all of these are true:

- clean files import cleanly
- messy but supported files recover through mapping or review
- unsafe files block clearly
- no known importer UI dead-end remains
- no known silent wrong-load case remains
- replay and truth coverage are broad enough to trust changes
- operators can classify stuck, failed, cancelled, review, and zero-change jobs
  quickly

## Non-Goals

This target model does not imply:

- supporting mixed-side imports
- supporting child-only `demande` imports
- supporting child-only `offer` imports
- removing grouped review
- rewriting the importer UI from scratch
