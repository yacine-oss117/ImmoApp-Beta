# Query Budget Guardrails

This project keeps a small query-budget contract to catch major performance
regressions early.

## Scope

`scripts/verify_query_budgets.py` seeds a tenant-scoped dataset and runs
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` against hot paths.

Current protected paths:

1. `match_client_counts`
   - built from `core.matcher.match_query_counts.build_client_counts_query`
   - represents the expensive matching/count path
2. `cache_lookup`
   - tenant-scoped read on `match_counts_cache`
   - represents the normal cache-read path

## Default budgets

- `IMMOAPP_QUERY_BUDGET_MATCH_MS=5000`
- `IMMOAPP_QUERY_BUDGET_CACHE_MS=250`
- `IMMOAPP_QUERY_BUDGET_ROWS=300`

These are intentionally conservative so local and CI runs stay stable.

## Tuning policy

- tighten only after repeated green runs
- re-baseline after infra shape changes
- do not silently disable the verifier in CI

## Output

The verifier writes timestamped JSON artifacts under:

- `scripts/benchmark_outputs/`
