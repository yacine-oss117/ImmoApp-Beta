# Queue Down Runbook

## Trigger
- Celery worker heartbeat missing
- Queue lag alert firing

## Immediate Actions
1. Check broker and worker status.
2. Confirm maintenance queue is draining.

## Triage Commands
- `docker compose ps rabbitmq worker beat`
- `docker compose logs --tail=200 worker`
- `docker compose logs --tail=200 rabbitmq`

## Recovery
1. Restart `worker` then `beat`.
2. Re-run one known maintenance task manually.
3. Verify task success events in observability.

## Rollback Decision
- If code deploy caused queue failures: rollback app image.
- If broker unstable: failover/restart broker and recheck durable queue state.
