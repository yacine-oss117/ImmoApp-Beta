# Match Scheduler Architecture

This document owns the `/matches/*/all` fairness scheduler and the durable
demande rebuild batch path.

## Two Different Systems

There are two related but different scheduling problems:

1. tenant-wide async `matches/*/all`
2. batched demande/offer/client/wilaya rebuild requests

They are not the same path and should not be reasoned about as one queue.

## Match-All Fair Share

Owner modules:

- `server/api/views_matches.py`
- `server/services/work_admission.py`
- `server/services/match_all_scheduler.py`
- `core/data/tenant_work_lease.py`

How it works:

- request hits `/matches/*/all`
- admission is checked first
- the DB lease is reserved before task launch
- stream-level coalescing prevents duplicate work
- per-tenant in-flight cap is computed from active tenants
- runtime profile can reduce the effective cap further

This is not AIMD. It is DB-backed fair-share with coalescing.

## Authoritative Owner Files

- match-all admission and response contract:
  `server/api/views_matches.py`
- match-all fair-share policy:
  `server/services/match_all_scheduler.py`
- shared work-class admission:
  `server/services/work_admission.py`
- durable demande rebuild dispatch state:
  `core/data/match_rebuild_state.py`
- durable batch scheduling and repair:
  `server/services/match_jobs.py`
  `server/api/tasks_match_pairs.py`
  `server/api/tasks_integrity.py`

If helper text disagrees with these files, these files win.

## Compatibility Only

These are useful implementation helpers, but not the architectural owner:

- `server/services/matches.py`
  matching domain logic, not scheduler authority
- `server/services/import_finalize_service.py`
  emits rebuild requests, but does not own match scheduling policy

## Durable Rebuild Dispatch

Owner modules:

- `server/services/match_jobs.py`
- `core/data/match_rebuild_state.py`
- `server/api/tasks_match_pairs.py`
- `server/api/tasks_integrity.py`

Durable fields in `match_rebuild_state`:

- `pending`
- `generation`
- `dispatch_after`
- `dispatch_claim_token`
- `dispatch_claim_expires_at`
- `last_requested_at`

This is now the source of truth for demande batching. Redis is no longer the
critical workflow queue.

## Offer Rebuilds

Offer rebuilds must stay batched. The correct helper is:

- `enqueue_rebuild_offer_pairs_batch()`

Do not regress to one-off enqueue loops unless a batch path is impossible.

## Failure / Repair Model

- stale pending rebuild rows are recovered by the janitor
- expired dispatch claims are reclaimed
- generation keeps the rebuild completion path safe against races

## What To Check When It Is Slow

1. `health/snapshot/`
2. `match_rebuild_health`
3. `match_runtime_profile*`
4. `tenant_work_lease` pressure for `matches_all`
5. pending demande rebuild count vs claimed count
