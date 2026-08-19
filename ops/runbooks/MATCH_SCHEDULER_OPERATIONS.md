# Match Scheduler Operations

## What To Check First

1. `health/snapshot/`
2. `match_rebuild_health`
3. `match_runtime_profile`
4. worker-match and worker-rebuild logs

## Bad Signs

- pending demande rebuilds rising while claimed rebuilds stay flat
- expired dispatch claims rising
- repeated `red` profile due to lock or statement timeouts
- match-all fair-share limit collapsing unexpectedly

## Repair Paths

- match janitor:
  `server/api/tasks_integrity.py`
- dispatch claim reclaim:
  `core/data/match_rebuild_state.py`

If pending rebuilds are stale, the first response is to verify the janitor and
dispatch claim recovery path, not to enqueue thousands of one-off manual tasks.

## Match-All Notes

- `/matches/*/all` is admin-only async work
- stream coalescing is expected
- fair-share limits are dynamic
- degraded admission is allowed and should be visible in responses
