# Migration Failure Runbook

## Trigger
- `immoapp_db_prepare` fails
- Application startup blocked by schema mismatch

## Immediate Actions
1. Freeze deploy rollout.
2. Capture failing migration/log output.

## Triage Commands
- `python -m alembic -c server/alembic.ini current`
- `python -m alembic -c server/alembic.ini history`
- `python scripts/verify_prod_config.py`

## Recovery
1. If safe, rerun migration after fixing env/permissions.
2. If not safe, rollback app image to previous migration-compatible release.
3. Re-run `immoapp_db_prepare` and smoke test.

## Rollback Decision
- Prefer app rollback over manual DB edits.
- Never use non-`alembic` schema modes (unsupported).
