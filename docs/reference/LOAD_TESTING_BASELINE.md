# Load Testing Baseline

## Goal

Catch obvious backend regression before release by combining query budgets,
runtime load, and API/queue latency checks.

## Guardrail layers

- `scripts/verify_query_budgets.py`
- `scripts/verify_load_baseline.py`
- `scripts/verify_api_queue_baseline.py`

## Baseline scenarios

- tenant-scoped search read path
- cache lookup path on `match_counts_cache`
- representative matching-count query path
- API request latency on hot CRM endpoints
- queue publish latency for background task dispatch

## Default profile

- seeded synthetic dataset
- short concurrent bursts, not long soak testing
- `p95` thresholds are configurable through env

Typical env controls:

- `IMMOAPP_LOAD_P95_SEARCH_MS`
- `IMMOAPP_LOAD_P95_CACHE_MS`
- `IMMOAPP_API_P95_CLIENTS_MS`
- `IMMOAPP_API_P95_LISTINGS_MS`
- `IMMOAPP_QUEUE_P95_PUBLISH_MS`
- `IMMOAPP_QUERY_BUDGET_*`

## Release rule

Any baseline failure blocks release until one of these is true:

- the query or index regression is fixed
- the code path is changed intentionally and the baseline is re-approved

This file is only the contract summary. Detailed numbers belong in the verifier
outputs, not in hand-maintained docs.
