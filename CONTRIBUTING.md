# Contributing

## Development setup

Use the supported bootstrap and runtime commands documented in:

- `docs/guides/CLEAN_MACHINE_BOOTSTRAP.md`
- `docs/guides/NEW_DEVELOPER_START.md`
- `scripts/README.md`

Before submitting a change, run the appropriate validation lane from `checks.ps1`.

## Architecture boundaries

Keep ownership explicit across layers:

- `app/views/` and `app/widgets/` render UI, collect input, and call `app/services/`. They should not access backend persistence directly.
- `app/services/` owns desktop orchestration, API calls, and UI-safe adapters.
- `server/api/` maps HTTP requests and responses. Business workflows belong in `server/services/` or `core/`.
- `server/services/` owns transactional workflows, authorization-sensitive operations, and asynchronous state transitions.
- `core/data/` owns persistence details and low-level data access.
- `core/contracts/` owns shared schemas, lifecycle constants, and pure domain contracts.

When a boundary needs to change, prefer an explicit interface or ownership move over cross-layer imports.

## Repository hygiene

Do not commit local runtime state or generated residue, including:

- `.tmp/`, `.cache/`, `.hypothesis/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- `__pycache__/`, `*.pyc`, logs, local databases, backups, and release outputs
- credentials, private keys, customer data, or machine-specific configuration
- downloaded tooling binaries that can be reproduced by setup scripts

## Code quality

- Add type hints to new public Python functions.
- Keep user-interface code thin and avoid blocking the GUI thread with network, database, or heavy compute work.
- Parameterize SQL and preserve transactional ownership for multi-table writes.
- Use explicit concurrency controls where stale or duplicated work can occur.
- Add regression tests for meaningful bug fixes and invariants.
- Keep tests deterministic; avoid arbitrary sleeps and weakened assertions.

## Security

Production configuration should fail closed. Authentication, authorization, tenant isolation, encryption, and session lifecycle changes require focused tests. Never add test-only bypasses to normal production paths.

See `docs/architecture/AUTH_AND_SECURITY.md` and `SECURITY.md`.

## Testing

The canonical entrypoints are:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File checks.ps1 -Stage pr
powershell -NoProfile -ExecutionPolicy Bypass -File checks.ps1 -Stage full
```

Native Windows desktop E2E tests are documented in `app/tests/e2e_desktop/README.md`.
