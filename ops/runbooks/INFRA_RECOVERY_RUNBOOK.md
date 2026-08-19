# Infra Recovery Runbook

This runbook gives you one repeatable path to recover local Docker infra, reseed OpenBao, rebuild app services, run migrations, and verify health.

## One-Command Recovery

Standard recovery:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/infra_recover.ps1
```

Standard recovery + admin user refresh:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/infra_recover.ps1 -SeedAdmin
```

## Hard Reset (DB Reinit)

Use only if DB cluster/auth is corrupted or schema/bootstrap is unrecoverable.
This moves current pgdata to backup and initializes a fresh cluster.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/infra_recover.ps1 -HardResetPgData -SeedAdmin
```

Backup location pattern:

- `C:\ProgramData\ImmoApp\backups\pgdata_reinit_YYYYMMDD_HHMMSS\pgdata_old`

## Optional Flags

- `-NoWindowsVolumes`: use only `deployment/compose/compose.yml` (skip `deployment/compose/compose.windows.yml`).
- `-SkipVolumeMismatchFix`: skip `scripts/fix_windows_volume_bind_mismatch.ps1`.
- `-SkipRebuildApp`: skip `web/worker/beat` image rebuild.
- `-RunPrChecks`: run `checks.ps1 -Stage pr` after recovery.
- `-RunFullChecks`: run `checks.ps1 -Stage full` after recovery.
- `-EnvFile <path>`: override env file (default is `C:\ProgramData\ImmoApp\config\.env.local`).

## What the Script Does

1. Stops stack (`down --remove-orphans`).
2. Optionally hard-resets `pgdata` with backup.
3. Fixes Windows bind-volume mismatch (unless skipped).
4. Starts infra + OpenBao init/seed + app-data-init.
5. Waits for health on `db/rabbitmq/valkey/minio/clamav/openbao`.
6. Rebuilds `web/worker/beat` images (unless skipped).
7. Recreates `web/worker/beat/caddy`.
8. Runs `python server/manage.py immoapp_db_prepare`.
9. Prints Alembic current revision.
10. Optionally seeds/updates `admin/admin`.
11. Verifies `http://127.0.0.1:8000/api/v1/health/` returns `200`.

## Post-Recovery Verification

Quick checks:

```powershell
docker compose --project-directory . --env-file C:\ProgramData\ImmoApp\config\.env.local -f deployment/compose/compose.yml -f deployment/compose/compose.windows.yml ps
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File checks.ps1 -Stage pr
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File checks.ps1 -Stage full
```

## Notes

- Keep OpenBao as source of truth for runtime secrets.
- If auth starts failing after reset, run with `-SeedAdmin` to restore `admin/admin`.
- If you need only normal lifecycle operations, `scripts/stack.ps1` remains the canonical day-to-day command wrapper.
