# Native Desktop E2E

This package contains the real Windows-native desktop E2E layer for the PySide6 client.

Stack:
- `pytest`
- `pywinauto` with `backend="uia"`
- real out-of-process `app/main.py`
- real local backend/runtime stack

This is not a widget-level test layer. These tests launch the desktop app as a separate process, drive real clicks/typing/dialogs/tabs, and assert both visible UI outcome and backend truth.

## Markers

- `e2e`: all native desktop end-to-end tests
- `e2e_smoke`: small PR/manual smoke journeys
- `e2e_nightly`: broader desktop journeys for nightly/manual runs

## Prerequisites

- Windows host
- interactive desktop session
- bootstrapped local runtime and both venvs
- local backend/runtime stack already running
- backend started with `IMMOAPP_E2E_TEST_MODE=1`
- backend identity verified against the current checkout before launch

Recommended stack entrypoints:
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_local_runtime.ps1`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke -RebuildBackend`

If you run the backend host-local instead of the Docker-local app runtime:
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_server.ps1`

The native E2E runner always performs a mandatory backend identity preflight. It calls
`GET /api/v1/e2e/runtime/identity/` with an authenticated disposable E2E user and
checks:

- E2E mode is enabled
- required E2E control routes are registered
- the running backend product-source fingerprint matches this checkout
- image-mode backends expose the Docker-build identity stamped during rebuild

If the backend is stale or not in E2E mode, the runner fails before launching the
desktop app. Expected preflight failures are printed as clean operator errors
without Python tracebacks.

Release validation also audits the rebuilt Docker backend dependency inventory.
The dependency target is named `docker-backend` and is generated from resolved
installed packages inside the image with `python -m pip freeze --all`; this
covers Linux-only backend packages that are not present in the Windows host venv.

## Runner Environment Preflight

Native E2E also validates the Windows runner before backend rebuild/identity
work. The default `scripts/test_e2e_desktop.ps1` path calls:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_e2e_environment.ps1 -Mode check -RequireInteractiveDesktop
```

Check mode is strictly report-only. It verifies the Windows host, interactive
desktop availability, PowerShell child-process spawning, server/client Python
launch, client Qt import, memory, commit/page-file headroom, disk space,
artifact-root state, and Docker availability when Docker cleanup/restart is
requested.

The runner does not require 6 GB free RAM to run. It warns below 6 GB, but fails
only when free RAM is critically low, commit/page-file headroom is critically
low, disk is short, or required process spawn canaries fail. The default
16 GB-machine thresholds are:

```text
WarnFreeMemoryGb = 6
MinCriticalFreeMemoryGb = 1
MinCommitHeadroomGb = 2
MinFreeDiskGb = 20
```

Override them explicitly when diagnosing a constrained runner:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_e2e_environment.ps1 -Mode check -RequireInteractiveDesktop -WarnFreeMemoryGb 6 -MinCriticalFreeMemoryGb 1 -MinCommitHeadroomGb 2
```

Use reset mode when the runner has accumulated stale E2E artifacts or orphaned
desktop test processes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_e2e_environment.ps1 -Mode reset -CleanArtifacts -KillStaleDesktopProcesses -RequireInteractiveDesktop -WarnFreeMemoryGb 6 -MinCriticalFreeMemoryGb 1 -MinCommitHeadroomGb 2
```

Reset mode only mutates known E2E-owned paths and command-line-verified E2E
processes. It never deletes broad temp folders, never deletes
`C:\ProgramData\ImmoApp`, and never kills generic `python.exe` or
`powershell.exe` processes by name. `-CleanArtifacts` prunes artifact children
older than `-ArtifactRetentionDays`; pass `-ArtifactRetentionDays 0` only when
you intentionally want to remove all current desktop E2E artifact children. If
Windows cannot provide command-line process ownership data, the script warns and
does not kill any process.

## Run Smoke

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke
```

If the Docker backend may be stale, use the supported green path:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke -RebuildBackend -ResetRunner -CleanArtifacts
```

The copied-file container sync path is intentionally unsupported for product
desktop E2E. Passing `-SyncContainers` or `-AllowSyncedContainer` fails fast;
use `-RebuildBackend` whenever the Docker backend may be stale.

The desktop client API timeout is runner-owned and defaults to 12 seconds. Use
`-ApiTimeoutSeconds` only for explicit diagnostics; accepted values are 3 to 60
seconds:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke -RebuildBackend -ApiTimeoutSeconds 20
```

Direct pytest equivalent:

```powershell
C:\ProgramData\ImmoApp\venvs\immoapp-server-py314\Scripts\python.exe -m pytest app/tests/e2e_desktop -m "e2e and e2e_smoke" --e2e-base-url http://127.0.0.1:8000 --e2e-client-python C:\ProgramData\ImmoApp\venvs\immoapp-client-py314\Scripts\python.exe --e2e-api-timeout-seconds 12 -v --tb=short
```

Passing runs delete their per-test artifacts automatically. To keep them for local debugging:

```powershell
$env:IMMOAPP_E2E_KEEP_PASSING_ARTIFACTS = "1"
```

The runner also supports explicit retention controls:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke -ArtifactRetentionDays 3
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke -KeepPassingArtifacts
```

## Run Broader Desktop Coverage

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite nightly
```

That runs:
- smoke journeys
- broader `e2e_nightly` journeys

## Current Canonical Journeys

Smoke:
- launch -> login success -> dashboard visible
- import happy path
- import review-required path
- create client
- create listing
- demande create/edit/delete through the Clients UI, with backend soft-delete truth
- offer create/edit/delete through the Properties UI, with backend soft-delete truth
  and preserved negotiability/accessibility/location fields across edit
- match screen load

Broader desktop journeys:
- invalid login -> retry success
- first-run setup + quick start
- import rejection/fail-safe
- import cancel
- edit client
- revoked session recovery on protected action
- server notification toast/unread badge
- transient backend failure on match flow
- demande mutation -> match result removal -> compatible mutation -> match result return
- offer mutation -> match result removal -> compatible mutation -> match result return
- contract lifecycle from matched listing -> create -> edit details -> print -> sign -> cancel -> soft-delete, with backend truth
- offer property photo upload/delete through the Properties UI, with MinIO-backed
  storage metadata truth and soft-delete truth
- agency settings save + reload

## Failure Artifacts

Each test writes artifacts under:

```text
.tmp/desktop_e2e_artifacts/
```

Per failed session the suite captures:
- full desktop screenshot
- UIA control tree dump
- process pid/exit code and child process tree
- visible top-level desktop windows
- redacted launch environment summary
- client stdio tail
- client `app.log` tail
- seeded desktop config files
- optional server log tail when `--e2e-server-log-path` is supplied

Passing runs do not retain these directories unless `--e2e-keep-passing-artifacts` or
`IMMOAPP_E2E_KEEP_PASSING_ARTIFACTS=1` is set.

Failed and manually kept artifact bundles are pruned at session start when they are older
than the retention window. The default is 7 days. Override it with:

```powershell
--e2e-artifact-retention-days 3
$env:IMMOAPP_E2E_ARTIFACT_RETENTION_DAYS = "3"
```

Use `0` to disable retention pruning. E2E client launches set
`PYTHONDONTWRITEBYTECODE=1`, so test appdata no longer accumulates `.pyc`
trees inside `.tmp/desktop_e2e_artifacts/`.

For release-style local validation, the wrapper performs a safe runner reset,
rebuilds the backend once, then runs the broad nightly suite. The nightly suite
already includes smoke-marked tests, so the wrapper avoids duplicate smoke
execution:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_e2e_release_validation.ps1
```

That reset step stops stale desktop and stale E2E server/preflight processes
only when command-line ownership proves they belong to this repo.

Recommended runner baseline for long smoke/nightly/full validation is at least
20 GB free disk on the repo/data drive, at least 2 GB commit/page-file headroom,
and a fresh interactive desktop session. Low free physical RAM alone is
diagnostic unless below the critical 1 GB threshold. A reboot or page-file
increase is still a valid recovery when PowerShell, Python, Qt import, Docker,
or commit-headroom checks fail, but targeted reset/preflight is the normal first
step.

## Selector Policy

- prefer `objectName` exposed through UIA automation id
- keep matching accessibility names on key controls
- avoid raw text-only selectors when a stable semantic id can exist

## Notes

- Offline sync/reconciliation is intentionally out of scope in this layer for now.
- Native desktop E2E is not wired into `checks.ps1 -Stage pr`.
- When the backend is missing, stale, or not ready, the suite fails fast with a precise readiness or identity message instead of hanging.
- The local-only backend control hooks are self-gated in `server/services/e2e_control.py`; runtime consumers no-op when disabled and direct E2E mutators raise.
- All `/api/v1/e2e/...` HTTP routes return 404 before authentication when E2E mode is disabled.
- The identity endpoint is authenticated when E2E mode is enabled, local/test-only, and does not expose secrets.
