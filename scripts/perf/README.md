# Performance Lane

This folder contains repeatable load-testing assets for a production-like local pass:

- `perf_seed_multitenant.py`: deterministic multi-tenant seed + cleanup utility.
- `k6_api_mix.js`: mixed foreground/read workload plus rebuild-contention scenario.
- `perf_match_pairs_capacity.py`: queue-level match-pairs throughput/latency benchmark.
- `explain_match_query_plan.py`: EXPLAIN ANALYZE capture for numeric match index decisioning.
- `collect_pg_match_health.py`: collect match-artifact health snapshots via DB or admin diagnostics.
- `compare_soak_reports.py`: compare first-hour vs last-hour soak drift and count-integrity results.

Use `scripts/run_perf.ps1` to run the end-to-end lane.
Use `scripts/run_chaos_short.ps1` for a shorter production-topology chaos pass with injected latency/jitter but without long soak semantics.

Recommended profiles:

- Baseline (healthy network + moderate load):
  - `.\scripts\run_perf.ps1 -Profile baseline -Tag baseline`
- Contention (added DB/Rabbit latency + higher tenant pressure):
  - `.\scripts\run_perf.ps1 -Profile contention -Tag contention`

High-tenant custom runs:

- Override active tenant fan-out explicitly:
  - `.\scripts\run_perf.ps1 -Profile custom -Tenants 1000 -RowsPerTenant 100 -ActiveManagers 120 -ActiveOwners 20 -ReadRate 110 -AuthRetryMax 20 -K6SetupTimeout 300s -Tag scale1000`
  - For very high fan-out setup, optionally skip cache warmup: add `-SkipWarmupReadCache`.
- Tiered matrix up to 1000 tenants:
  - `.\scripts\perf\run_capacity_matrix.ps1 -Duration 120s -OutputTag capacity`

The generated `perf_report_<tag>.json` includes:

- top-line read `p95/p99`
- request failure rate
- per-endpoint read latency trends (`clients`, `listings`, `users`, `invites`, `notifications`)
- network contention parameters used for that run

Match-pairs queue capacity check:

- `python scripts/perf/perf_match_pairs_capacity.py --tag <same-tag> --tenants 1000 --demandes-per-tenant 1`
- Output: `scripts/perf_outputs/match_pairs_capacity_<tag>.json`
- Batch mode (tenant-chunked): `python scripts/perf/perf_match_pairs_capacity.py --tag <same-tag> --tenants 200 --demandes-per-tenant 1000 --mode batch --demande-batch-size 100`

Numeric filter plan check:

- `python scripts/perf/explain_match_query_plan.py --tag <same-tag> --sample-demandes 200`

Long-run soak support:

- `python scripts/perf/collect_pg_match_health.py --mode db --output scripts/perf_outputs/match_health.jsonl --jsonl`
- `python scripts/perf/compare_soak_reports.py --k6-summary <summary.json> --pulse-jsonl <pulses.jsonl> --health-jsonl <health.jsonl> --count-jsonl <count_checks.jsonl> --output <report.json>`
