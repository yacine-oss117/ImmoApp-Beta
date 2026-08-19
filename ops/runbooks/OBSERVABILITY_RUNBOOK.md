# Observability Runbook (SigNoz + OpenTelemetry)

## Goal
Provide minimum production-grade monitoring on a single server:
- traces
- metrics
- log correlation
- alerting

## Services and data flow
1. `web`, `worker`, `beat` emit OTEL data.
2. Data goes to `otel-collector` (OTLP HTTP `:4318`).
3. SigNoz stores and serves data via ClickHouse + query-service + frontend.

## Startup
Windows:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-full -UseWindowsVolumes
```

Linux:
```bash
make up-full
```

## Auto-provision channels and alerts
After SigNoz is up, provision alert channels/rules from source-controlled config:

Windows:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/provision_signoz_alerts.ps1
```

Linux:
```bash
make signoz-provision-alerts
```

Config file:
- `deployment/docker/signoz/provisioning/alerts.json`

Notes:
- The default channel is `immoapp-email` and resolves destination from `SIGNOZ_ALERT_EMAIL_TO`.
- Auth can use either `SIGNOZ_API_KEY` or `SIGNOZ_EMAIL` + `SIGNOZ_PASSWORD` + `SIGNOZ_ORG_ID`.
- First-run bootstrap is supported via `SIGNOZ_BOOTSTRAP_EMAIL` + `SIGNOZ_BOOTSTRAP_PASSWORD`.
- For Gmail SMTP, set:
  - `SIGNOZ_EMAILING_ENABLED=1`
  - `SIGNOZ_EMAILING_FROM=<your-email>`
  - `SIGNOZ_EMAILING_ADDRESS=smtp.gmail.com:587`
  - `SIGNOZ_EMAILING_AUTH_USERNAME=<your-email>`
  - `SIGNOZ_EMAILING_AUTH_PASSWORD=<gmail-app-password>`

## Verify telemetry is flowing
1. Open SigNoz UI: `http://localhost:3301`
2. Go to `Services`
3. Confirm these services are present:
   - `immoapp-server`
   - `immoapp-worker`
   - `immoapp-beat`
4. Hit a few API endpoints from client/server.
5. Check new traces appear in `Traces`.

## Importer telemetry checks

Before importer canary, confirm importer telemetry includes these dimensions in
metrics or correlated logs:

- `terminal_reason`
- `wait_state`
- `stalled_reason`
- `mapping_palette_mode`
- `manual_mapping_required`
- `result_zero_change`
- `cancel_requested`
- `repair_attempted`
- `requeued_after_lease_expiry`

Current importer signal sources:

- preview mapping diagnostics
- finalize terminal execution metrics
- stalled-job watchdog events
- expired phase requeue events

Interpretation:

- `wait_state = queued`
  - waiting behind another agency-scoped import
- `wait_state = waiting_for_worker`
  - accepted into execution, but no worker phase has started yet
- `stalled_reason = worker_not_picked_up`
  - stale start, not active phase work
- `terminal_reason = zero_change`
  - finished cleanly with no created or updated rows
- `mapping_palette_mode = recovery_union`
  - weak same-side bundle recovery path was used

## Must-have alerts (initial set)
Create these 6 alerts:

1. API 5xx rate (Critical)
- Condition: `(5xx / requests) > 2%`
- Window: 5 minutes

2. API latency p95 (Warning/Critical)
- Warning: `p95 > 800ms` for 10 minutes
- Critical: `p95 > 1500ms` for 5 minutes

3. Celery task failures (Critical)
- Condition: failures > 5 in 10 minutes

4. Queue backlog (Critical)
- Condition: queue depth > 100 for 10 minutes
- Adjust threshold to your baseline.

5. DB connection saturation (Critical)
- Condition: active connections > 85% max for 5 minutes

6. Disk free space (Critical)
- Condition: free disk < 15% on data volumes

## Business dashboards (matcher + storage)
Create these dashboard panels in SigNoz using span-name filters.

1. Match Rebuild Duration (p95)
- Source: traces
- Filter: `span.name = "matcher.task.rebuild_pairs_for_demande"`
- Group by: `match.agency_id`
- Chart: p50/p95 duration (ms)
- Target: p95 < 3000ms in normal load

2. Match Rebuild Throughput
- Source: traces
- Filter: `span.name = "matcher.task.rebuild_pairs_for_demande"`
- Use attributes:
  - `match.pairs_stored`
  - `match.candidates_total`
- Chart: sum per 5m

3. Match Read Latency
- Source: traces
- Filter: `span.name IN ("matcher.fetch_matches_for_demande","matcher.fetch_matches_for_client")`
- Chart: p50/p95 duration
- Target: p95 < 500ms on warm cache

4. Storage Upload Completion Latency
- Source: traces
- Filter: `span.name = "storage.complete_presigned_upload"`
- Chart: p50/p95 duration
- Target: p95 < 2000ms (without virus scan), < 6000ms (with scan)

5. Storage Presign Latency
- Source: traces
- Filter: `span.name = "storage.generate_presigned_upload"`
- Chart: p95 duration
- Target: p95 < 300ms

6. Storage Delete/Purge Activity
- Source: traces
- Filter:
  - `span.name = "storage.mark_deleted"`
  - `span.name = "storage.purge_deleted_objects"`
- Chart: count + p95 duration

## Business alerts (matcher + storage)
Add these alerts in addition to infrastructure alerts.

1. Matcher Rebuild Slow (Warning/Critical)
- Query: traces where `span.name = "matcher.task.rebuild_pairs_for_demande"`
- Warning: p95 > 3s for 10m
- Critical: p95 > 7s for 5m

2. Matcher Rebuild Error Rate (Critical)
- Query: traces where `span.name = "matcher.task.rebuild_pairs_for_demande"` and status=error
- Condition: error rate > 2% for 10m

3. Match Read Slow (Warning)
- Query: traces where `span.name IN ("matcher.fetch_matches_for_demande","matcher.fetch_matches_for_client")`
- Condition: p95 > 800ms for 10m

4. Storage Completion Failures (Critical)
- Query: traces where `span.name = "storage.complete_presigned_upload"` and status=error
- Condition: failures > 5 in 10m

5. Storage Presign Failures (Warning/Critical)
- Query: traces where `span.name = "storage.generate_presigned_upload"` and status=error
- Warning: failures > 3 in 10m
- Critical: failures > 10 in 10m

## Match Artifact Rebuild Rollout Checks
These checks are required when rolling out the direct `match_candidates` + `match_pairs` rebuild pipeline.

1. Dead tuples and stale stats
- Monitor `pg_stat_user_tables` for both `match_candidates` and `match_pairs`:
  - `n_dead_tup`
  - `last_autovacuum`
  - `autovacuum_count`
  - `last_autoanalyze`
  - `autoanalyze_count`
- The rebuild path is still `DELETE + INSERT`, so dead tuples are expected.
- The shipped table reloptions are:
  - `autovacuum_vacuum_scale_factor = 0.02`
  - `autovacuum_vacuum_threshold = 2000`
  - `autovacuum_vacuum_insert_scale_factor = 0.05`
  - `autovacuum_vacuum_insert_threshold = 5000`
  - `autovacuum_analyze_scale_factor = 0.01`
  - `autovacuum_analyze_threshold = 1000`
- If dead tuples still accumulate across perf or staging runs, create a separate table-specific follow-up tuning plan before wider rollout.

2. Temp spill detection
- Run the explain gate for both `legacy` and `direct` pipelines.
- Watch:
  - `temp read blocks`
  - `temp written blocks`
  - `sort_spill_nodes`
  - `hash_spill_nodes`
- If the direct pipeline spills, first reduce:
  - `IMMOAPP_MATCH_PAIRS_TASK_CHUNK_SIZE`
  - `IMMOAPP_MATCH_PAIRS_FULL_SQL_THRESHOLD`
- Do not jump straight to app-managed `work_mem` tuning.

3. Acceptance rule
- The direct pipeline is not accepted if it improves compute throughput but regresses mixed-read latency.
- Keep the feature flag on `legacy` until:
  - correctness tests pass
  - explain output is clean enough for the chosen chunk size
  - mixed-read benchmark stays within baseline
  - compute benchmark materially improves
- The measured single-node default for the dedicated `match_pairs` worker is `CELERY_MATCH_PAIRS_CONCURRENCY_DOCKER=3`.
- Raising it above `3` should be treated as a fresh perf experiment, not a blind default change.

## Match Artifact Soak-Hardening
These checks turn the optimized match pipeline into a long-run operational contract.

### Sampling cadence
- `snapshot_postgres_match_health` runs every `300` seconds on the `maintenance` queue.
- The adaptive profile controller stores a shared profile state in cache:
  - `green`
  - `yellow`
  - `red`

### Runtime profiles
- `green`
  - `IMMOAPP_MATCH_PAIRS_DEMANDE_BATCH_SIZE=250`
  - `IMMOAPP_MATCH_PAIRS_TASK_CHUNK_SIZE=1000`
  - `IMMOAPP_MATCH_PAIRS_FULL_SQL_THRESHOLD=250`
- `yellow`
  - `demande_batch_size=200`
  - `task_chunk_size=750`
  - `full_sql_threshold=200`
- `red`
  - `demande_batch_size=125`
  - `task_chunk_size=500`
  - `full_sql_threshold=125`

### Transition rules
Enter `yellow` after 2 consecutive samples if any are true:
- dead ratio on `match_candidates` or `match_pairs` is `>= 0.15`
- estimated index bloat on either table is `> 500 MiB`
- autovacuum lag is `>= 1200s` with at least `50000` dead tuples
- temp bytes delta over 5 minutes is `>= 128 MiB`
- active connection ratio is `>= 0.80`
- statement timeout delta over 5 minutes is `>= 1`
- lock timeout delta over 5 minutes is `>= 1`

Enter `red` after 2 consecutive samples if any are true:
- dead ratio on `match_candidates` or `match_pairs` is `>= 0.25`
- estimated index bloat on either table is `> 1 GiB`
- autovacuum lag is `>= 2400s` with at least `100000` dead tuples
- temp bytes delta over 5 minutes is `>= 512 MiB`
- active connection ratio is `>= 0.90`
- statement timeout delta over 5 minutes is `>= 3`
- lock timeout delta over 5 minutes is `>= 3`

Recoveries:
- `red -> yellow` requires 6 healthy samples (`30 minutes`)
- `yellow -> green` requires 12 healthy samples (`60 minutes`)

### Stale and cold-start safety
- If health samples are older than `IMMOAPP_MATCH_PROFILE_SAMPLE_STALE_SECONDS`:
  - fall back to `yellow`
  - reason: `stale_health_snapshot_fail_safe`
- If profile cache state is unavailable:
  - fall back to `yellow`
  - reason: `cache_unavailable`
- On first boot with no cached profile:
  - start at `yellow`
  - reason: `cold_start_no_baseline`
  - require 2 healthy green-evaluating samples before entering `green`

### Count-integrity validation during soak
- After every hourly compute pulse, run a count spot-check on sampled clients from the rebuilt agency.
- Compare:
  - cache-backed counts from `POST /api/v1/cache/match/get/`
  - direct recompute counts from `POST /api/v1/matches/clients/counts/`
- Poll every `5` seconds for up to `60` seconds.
- Success rule:
  - every sampled client count matches within `60` seconds
- Failure rule:
  - any remaining mismatch is a `count_integrity_failure`
  - block release until resolved

### Nightly 6h soak acceptance
- read p95 `<= 30ms`
- read p99 `<= 120ms`
- HTTP failed rate `<= 0.001`
- last-hour read p95 drift `<= 35%`
- last-hour read p99 drift `<= 50%`
- compute pulse throughput drift `<= 15%`
- compute pulse p95 drift `<= 20%`
- no task timeouts
- no unhandled task failures
- no `dead_ratio > 0.25` for more than 2 consecutive samples
- `last_autovacuum` and `last_autoanalyze` advance for both match tables
- `temp_bytes_delta_5m < 512 MiB`
- `count_integrity_failures_total = 0`

### Pre-release 24h soak acceptance
- read p95 `<= 35ms`
- read p99 `<= 150ms`
- HTTP failed rate `<= 0.001`
- last-hour read p95 drift `<= 40%`
- last-hour read p99 drift `<= 60%`
- compute pulse throughput drift `<= 20%`
- compute pulse p95 drift `<= 25%`
- no red-profile lock-in beyond `30` consecutive minutes
- no `dead_ratio > 0.25` for more than 2 consecutive samples
- autovacuum and autoanalyze keep advancing
- temp spill stays below red thresholds
- `count_integrity_failures_total = 0`

### What to do on yellow
- confirm autovacuum is advancing on both match tables
- inspect temp-bytes delta and active connection ratio
- do not raise match batch sizes while yellow is active
- keep the system running; the profile should already be downshifting automatically

### What to do on red
- inspect `pg_stat_activity` for long-running queries and lock waits
- inspect match task timeout deltas
- consider temporarily lowering `CELERY_MATCH_PAIRS_CONCURRENCY_DOCKER`
- do not manually vacuum during a soak unless immediate recovery is required and the run is already considered failed

### Soak failure remediation
Dead-ratio breach:
- check `autovacuum_vacuum_cost_delay`; consider lowering to `5ms`
- check `maintenance_work_mem`; consider increasing to `256MB`
- if immediate recovery is required:
  - `VACUUM (VERBOSE) match_candidates;`
  - `VACUUM (VERBOSE) match_pairs;`

Read p95 drift breach:
- inspect index bloat with `pgstatindex('match_pairs_pkey')`
- if `avg_leaf_density < 50%`, run `REINDEX CONCURRENTLY`

Compute throughput collapse:
- inspect `pg_stat_activity` for long-running queries and lock waits
- confirm whether active connection ratio is near threshold
- consider temporarily lowering `CELERY_MATCH_PAIRS_CONCURRENCY_DOCKER`

Temp-bytes spike:
- inspect the current `work_mem`
- if needed, try `SET LOCAL work_mem = '16MB'` for the rebuild session as a targeted remediation

## Regression guardrail (required)
- Keep span names stable:
  - `matcher.compute_pairs_for_demande`
  - `matcher.fetch_matches_for_demande`
  - `matcher.fetch_matches_for_client`
  - `matcher.task.rebuild_pairs_for_demande`
  - `storage.generate_presigned_upload`
  - `storage.complete_presigned_upload`
  - `storage.generate_download_url`
  - `storage.mark_deleted`
  - `storage.purge_deleted_objects`
- CI check: `scripts/verify_business_spans_instrumented.py`

## Incident checklist
1. Inspect alert details in SigNoz.
2. Correlate with traces/logs (same time window).
3. If queue issues:
   - verify `worker`, `rabbitmq`, `valkey` health.
4. If latency issues:
   - inspect slow traces and DB spans.
5. If disk issues:
   - purge old telemetry retention first, then app artifacts.

## Retention and cost/sizing
- Current default retention: 60 days (`SIGNOZ_TTL_HOURS=1440`).
- If disk is tight, reduce to 7-14 days during early launch.

## Single-server reality
- This setup is valid for launch.
- If server fails, app and monitoring fail together.
- Next maturity step: move observability to a separate host.
