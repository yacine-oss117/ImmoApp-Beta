# Restore Drill Runbook

## Policy
- Run monthly.
- Store proof artifact (timestamp + result + operator).

## Procedure
1. Generate backup artifact.
2. Restore into isolated temporary database.
3. Run:
   - schema/security verification
   - tenant smoke read/write checks

## Commands
- `powershell -ExecutionPolicy Bypass -File scripts/db_backup.ps1`
- `IMMOAPP_RUN_RESTORE_DRILL=1 python scripts/verify_restore_drill_execution.py`

## Success Criteria
- Restore completes without SQL errors.
- Alembic version table present.
- Tenant isolation smoke passes.

## Failure Response
1. Open incident.
2. Fix backup/restore breakage.
3. Re-run until green.
