# Performance Profiles

These are the standard perf profiles for fast iteration and medium confidence.

## Quick Create

Script profile:

- `scripts/run_import_perf.ps1 -Profile quick_create`

- `Tenants=4`
- `SeedRowsPerTenant=150`
- `ImportsPerTenant=1`
- `RowsPerImport=250`
- `Concurrency=3`
- `ImportWorkerReplicas=2`
- `Scenario=child_mix`
- `ReviewEvery=0`
- `DuplicateStrategy=allow_all`
- `PreviewFraction=0`

Target:

- `100%` success
- end-to-end p95 `<= 4.0s`
- throughput `>= 180 rows/s`

## Quick Review

Same as quick create, except:

Script profile:

- `scripts/run_import_perf.ps1 -Profile quick_review`

- `ReviewEvery=17`
- `DuplicateStrategy=review`

Target:

- `100%` success
- end-to-end p95 `<= 6.0s`
- throughput `>= 150 rows/s`

## Medium Create

Script profile:

- `scripts/run_import_perf.ps1 -Profile medium_create`

- `Tenants=8`
- `SeedRowsPerTenant=250`
- `ImportsPerTenant=1`
- `RowsPerImport=400`
- `Concurrency=4`
- `ImportWorkerReplicas=2`
- `Scenario=child_mix`
- `ReviewEvery=0`
- `DuplicateStrategy=allow_all`

Target:

- `100%` success
- end-to-end p95 `<= 6.0s`
- throughput `>= 400 rows/s`

## Medium Review

Same as medium create, except:

Script profile:

- `scripts/run_import_perf.ps1 -Profile medium_review`

- `ReviewEvery=15`
- `DuplicateStrategy=review`

Target:

- `100%` success
- end-to-end p95 `<= 9.0s`
- throughput `>= 250 rows/s`

## Why These Profiles Exist

Use quick profiles for inner-loop tuning.

Use medium profiles for confirmation after code is already stable.

Do not use long chaos soaks as the inner optimization loop.

Compatibility note:

- `quick` remains as a compatibility alias for the old review-heavy quick path.
