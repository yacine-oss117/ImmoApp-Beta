# New Developer Start

> **Fastest evaluation path:** from the repository root, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\quickstart.ps1`. It creates the isolated Python environments, generates local Beta credentials, starts the complete Docker backend, checks health, and launches the desktop client.

Use this file when you are new to the repo and need a reliable reading order.

## Read in this order

1. `README.md`
2. `docs/guides/CLEAN_MACHINE_BOOTSTRAP.md`
3. `docs/guides/ENV_RUNTIME.md`
4. `docs/guides/RUNTIME_AUTHORITY.md`
5. `docs/guides/STACK.md`
6. `docs/guides/OPENBAO_SETUP.md`
7. `docs/architecture/CODEBASE_MAP.md`
8. `app/tests/e2e_desktop/README.md`
9. `docs/architecture/RUNTIME_AND_DATA_FLOWS.md`
10. `docs/architecture/IMPORTER_ARCHITECTURE.md`
11. `docs/architecture/MATCHING_AND_CACHE_ARCHITECTURE.md`
12. `docs/architecture/CRM_LIFECYCLE.md`
13. `docs/architecture/STORAGE_AND_MEDIA.md`
14. `docs/architecture/AUTH_AND_SECURITY.md`
15. `docs/reference/API_ROUTE_REFERENCE.md`
16. `docs/reference/DB_SCHEMA_REFERENCE.md`
17. `docs/reference/DB_TABLE_CATALOG.md`

That order gives you:

- what the system is
- how it runs locally
- where code lives
- how requests, jobs, and data move
- how the biggest product subsystems are split
- the exact current route and table surface

## First commands

Canonical clean-machine bootstrap:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_local_runtime.ps1
```

Then continue with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-infra -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_openbao_identity.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action db-prepare -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-app -UseWindowsVolumes
```

Quality gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File checks.ps1 -Stage pr
```

Desktop client:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_client.ps1
```

Native desktop E2E smoke. The runner verifies the backend identity before it
launches the desktop app:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke
```

If Docker may contain stale server code, use the supported rebuild path. The
native E2E identity preflight requires the backend image build identity to match
this checkout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke -RebuildBackend
```

Copied-file container sync is intentionally rejected for product desktop E2E.
Use `-ApiTimeoutSeconds 3..60` only when diagnosing API latency; the default is
12 seconds:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 -Suite smoke -RebuildBackend -ApiTimeoutSeconds 20
```

Host-local server debug only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_server.ps1
```

## Mental model

- `app/` is the Qt thin client
- `server/` is the HTTP, task, runtime, and persistence server
- `core/` holds shared domain logic used across runtimes
- `deployment/` holds machine/runtime manifests
- `docs/` is the human-oriented owner-doc set
- generated references under `docs/reference/` are intended to be exact
- Docker-local is the primary supported local runtime
- host-local server/client mode is secondary and debug-only
- native desktop E2E is Windows-only and drives the real PySide6 app process
- native desktop E2E fails before desktop launch if the backend is stale or E2E mode is disabled
- runtime state lives under `C:\ProgramData\ImmoApp`

## How to trace a feature

UI-driven feature:

1. start in `app/views/` or `app/widgets/`
2. follow into `app/services/`
3. look for the API call or local orchestration point
4. jump to `server/api/views_*.py`
5. follow into `server/services/`
6. finish in `server/pg/`, `core/data/`, `core/importer/`, or `core/matcher/`

Server-only feature:

1. start from `docs/reference/API_ROUTE_REFERENCE.md`
2. open the listed view function
3. follow the called service module
4. inspect the repository/UoW or task module behind it

## Generated truth

These files are generated and should be treated as exact current reference:

- `docs/reference/API_ROUTE_REFERENCE.md`
- `docs/reference/DB_TABLE_CATALOG.md`

If they drift, regenerate them:

```powershell
python scripts/generate_api_route_reference.py
python scripts/generate_db_table_catalog.py
```

## Test Artifact Hygiene

- Native desktop E2E artifacts are written under `.tmp/desktop_e2e_artifacts/`.
- Passing E2E tests delete their own artifacts automatically.
- Failed E2E tests retain diagnostics: screenshots, UIA trees, process trees,
  visible desktop windows, redacted launch environment, config snippets, client
  stdio tails, and log tails.
- Retained failed or manually kept E2E artifacts are pruned by age at session
  start. The default retention is 7 days.
- Use `-KeepPassingArtifacts` or `IMMOAPP_E2E_KEEP_PASSING_ARTIFACTS=1` only
  while debugging a local run.
