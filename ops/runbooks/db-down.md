# DB Down Runbook

## Trigger
- API errors spike with DB connection failures
- `/api/v1/health/` reports DB unhealthy

## Immediate Actions
1. Check Postgres container/service health.
2. Verify credentials/env (`POSTGRES_*`) and network reachability.
3. Scale down write traffic if needed (maintenance mode).

## Triage Commands
- `docker compose ps db`
- `docker compose logs --tail=200 db`
- `python scripts/check_schema.py`

## Recovery
1. Restart DB service.
2. Run `python server/manage.py immoapp_db_prepare`.
3. Run tenant smoke:
   - login
   - one read
   - one write

## Rollback Decision
- If migration-related outage: rollback app image, keep DB intact.
- If data corruption suspected: execute restore drill runbook.
