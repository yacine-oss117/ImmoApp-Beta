# Storage Down Runbook

## Trigger
- MinIO health fails
- Upload/download endpoints return storage errors

## Immediate Actions
1. Check MinIO status and bucket policy.
2. Confirm credentials and endpoint reachability.

## Triage Commands
- `docker compose ps minio`
- `docker compose logs --tail=200 minio`
- `python scripts/verify_infrastructure_hardening.py`

## Recovery
1. Restart MinIO.
2. Validate presign endpoint and one test upload.
3. Confirm object metadata write in DB succeeds.

## Rollback Decision
- If storage config broke after deploy, rollback compose/app config to previous known-good values.
