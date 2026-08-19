# SLO And Release Guardrails

This document defines the minimum production operating posture for ImmoApp.

## SLO Targets

Service level objectives are measured per rolling 30-day window.

- API availability: `>= 99.9%`
- `/api/v1/health/` p95 latency: `<= 150ms`
- `/api/v1/dashboard/` p95 latency: `<= 700ms`
- Match cache read endpoints p95 latency: `<= 300ms`
- Background task success rate: `>= 99.5%`

## Error Budget

- Monthly error budget for API availability: `0.1%`
- If budget burn rate exceeds `2x` over 1 hour:
  - freeze non-critical deploys
  - run incident triage
  - resume only after mitigations are deployed

## Alert Thresholds

- 5xx rate > `2%` for 5 minutes
- p95 latency > target for 10 minutes
- Celery queue lag > `5 minutes` for maintenance queue
- DB connection pool exhaustion warnings
- Restore drill failure or stale last-success timestamp

## Canary Rollout

1. Deploy to canary instance (single worker)
2. Route 5% of traffic for 15 minutes
3. Validate:
   - no SLO alert firing
   - no new error-class spikes
   - no tenant isolation alarms
4. Increase to 25%, then 100% if healthy

Automation command:

- `powershell -ExecutionPolicy Bypass -File .\scripts\release_canary.ps1 -NewImage <registry/image:tag> -PreviousImage <registry/image:tag>`
- Optional fast path (skip live smoke): add `-SkipLiveSmoke`.

## Rollback Playbook

1. Trigger immediate rollback to previous image tag
2. Drain canary traffic to zero
3. Verify:
   - health endpoint
   - one tenant write/read smoke
   - Celery worker heartbeat
4. Open post-incident report with root cause and prevention action

Automation command:

- `powershell -ExecutionPolicy Bypass -File .\scripts\release_rollback.ps1 -PreviousImage <registry/image:tag>`

## Emergency Kill Switches

- Disable tenant-wide expensive recompute triggers immediately:
  - `IMMOAPP_DISABLE_MATCH_ALL_ENDPOINTS=1`
  - Affects `/api/v1/matches/*/all/` endpoints (returns `503 MATCH_ALL_DISABLED`).

## On-call Runbook

- Every alert maps to:
  - an owner role
  - triage query/command
  - rollback decision tree
- Incident notes are mandatory for every P1/P2 page.
