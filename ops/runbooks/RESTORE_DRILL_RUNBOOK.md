# Restore Drill Runbook

This runbook validates that backups are restorable and the restored database is operational.
For beta and later media-bearing environments, database-only restore evidence is
insufficient. The release pass fails unless the drill also restores object storage
and verifies active photo/storage rows have recoverable object bytes.

## Prerequisites
- PostgreSQL client tools available either:
  - in `PATH` (`pg_dump`, `pg_restore`, `psql`), or
  - via explicit env overrides:
    - `IMMOAPP_PG_DUMP_PATH`
    - `IMMOAPP_PG_RESTORE_PATH`
- Admin DB credentials in environment:
  - `POSTGRES_ADMIN_USER`
  - `POSTGRES_ADMIN_PASSWORD`
  - `POSTGRES_HOST` (optional, default `127.0.0.1`)
  - `POSTGRES_PORT` (optional, default `5432`)
- Server venv available at the standard ImmoApp path

## 1) Create backup
```powershell
powershell -ExecutionPolicy Bypass -File scripts/db_backup.ps1
```

For beta release proof, create a database plus object-storage bundle instead.
This command first runs a read-only release integrity check. If orphan rows or
`ready` storage rows with missing object bytes are found, it fails before
`pg_dump` and does not repair or delete data:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/backup_release_bundle.ps1
```

For disposable local development data only, use the explicit repair tool. It is
dry-run by default and requires both confirmation and apply flags before it
mutates known orphan residue or soft-deletes local `ready` storage metadata
whose object bytes are already missing:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/repair_local_dev_release_integrity.ps1
powershell -ExecutionPolicy Bypass -File scripts/repair_local_dev_release_integrity.ps1 -ConfirmDisposableLocalData -Apply
```

This is not a production data repair strategy.

## 2) Run restore drill
Use the generated `.dump` file:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/db_restore_drill.ps1 -BackupFile "C:\ProgramData\ImmoApp\backups\immoapp_YYYYMMDD_HHMMSS.dump"
```

For beta release proof, restore the release bundle. This verifies
`manifest.json` and SHA-256 hashes before touching the database or object
storage, restores PostgreSQL into a clean drill database, mirrors MinIO/S3
objects into an isolated `immoapp-restore-drill-*` bucket, and verifies active
storage rows against that isolated bucket. Verification compares each restored
`ready` storage object against the bundle manifest byte count and SHA-256 hash;
object existence alone is not valid proof:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore_release_bundle.ps1 -BundlePath "C:\ProgramData\ImmoApp\backups\release_YYYYMMDD_HHMMSS.zip"
```

The beta restore drill must not mirror objects into the live source bucket.
Production restore is a separate operational procedure with separate approval
and destructive-restore controls.

The beta validation orchestrator runs the same backup/restore proof and records
the bundle path, restore database, isolated restore bucket, and object hash
verification counts:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_beta_release_validation.ps1
```

That wrapper does not run local-dev repair automatically. Dirty pre-backup
integrity remains a NO-GO until a human fixes production data or explicitly runs
the disposable-local repair path for local development data only.

## 2b) Automated restore verification (CI/scripted)
```bash
IMMOAPP_RUN_RESTORE_DRILL=1 python scripts/verify_restore_drill_execution.py
```

This command performs:
- `pg_dump` from the configured primary DB
- restore into an isolated temporary DB
- post-restore schema sanity check (`alembic_version`)
- tenant smoke checks (write/read under tenant A + isolation check from tenant B)
- cleanup (drops the temporary DB)

Tooling behavior:
- If host `pg_dump/pg_restore` are available, they are used directly.
- If missing, the verifier automatically falls back to `docker compose exec db ...`
  and performs dump/restore via the running DB container.
- Override compose files with `IMMOAPP_COMPOSE_FILES` (semicolon-separated), e.g.
  `IMMOAPP_COMPOSE_FILES=deployment/compose/compose.yml;deployment/compose/compose.windows.yml`.

## 3) Expected verification
The drill is successful if:
- restore completes without SQL errors
- `scripts/verify_security_schema.py` passes
- `server/manage.py test api.tests.test_firewall --noinput` passes
- release bundle verification passes for active storage objects when media rows exist
- release bundle manifest/hash verification passes before restore actions
- active storage rows verify against the isolated restore bucket

## Operational policy
- Run this drill at least monthly
- Keep drill evidence (timestamp, backup file path, command output)
- Rotate and securely store backup artifacts per security policy
- Pair database restore evidence with object-storage restore evidence before
  declaring media-bearing environments recoverable.
- Treat a restored database with missing photo objects as a beta blocker, not a
  warning.
- Treat dirty pre-backup integrity, manifest/hash mismatch, FK restore failure,
  or missing object bytes as beta NO-GO.
