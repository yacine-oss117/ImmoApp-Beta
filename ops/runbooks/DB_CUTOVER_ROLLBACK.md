# DB Cutover Rollback Runbook

## Scope
This runbook covers rollback for the Alembic-only runtime schema cutover.

## Preconditions
1. Take a verified database snapshot/backup immediately before deployment.
2. Deploy application and migration changes in a maintenance window.
3. Keep previous application artifact/build available for fast rollback.

## Failure Modes
1. Migration failure during deploy.
2. Post-migration application startup/login failure.
3. Post-migration functional/security regression.

## Rollback Strategy
The baseline cutover is restore-based. `downgrade()` is intentionally no-op for the baseline/cutover revisions.

## Procedure
1. Stop application services (server workers, API process, desktop clients if applicable).
2. If migrations failed or runtime is unhealthy, do not continue forward fixes on production DB.
3. Restore the pre-cutover snapshot to the target database instance.
4. Redeploy the previous known-good application build.
5. Start services and verify:
   1. API health endpoint responds.
   2. Authentication works (`admin/admin` in controlled environment).
   3. Core flows (clients/listings/match/CRM) load without exceptions.
6. Capture incident notes:
   1. failing migration revision,
   2. error output,
   3. restore start/end times,
   4. verification evidence.

## Post-Rollback
1. Keep cutover branch frozen until root cause is fixed.
2. Re-run dry-run validation:
   1. `scripts/verify_alembic_fresh_chain.py`
   2. `scripts/verify_security_schema.py`
   3. full check lane in staging.
3. Schedule a new maintenance window for re-attempt.
