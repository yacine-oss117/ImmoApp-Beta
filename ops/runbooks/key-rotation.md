# Key Rotation Runbook

## Scope
- ALE key rotation
- Storage/KMS key rotation procedures

## Pre-checks
1. Confirm maintenance window.
2. Ensure current backups and restore drill are green.
3. Confirm worker/queue health.

## ALE Rotation
1. Trigger rotation task.
2. Reindex/search-key jobs complete.
3. Verify encryption/decryption audits pass.

## Storage/KMS Rotation
1. Rotate key material in KMS/HSM.
2. Re-encrypt data keys/object keys as required.
3. Verify upload/download flows and audit trails.

## Validation
- `python scripts/verify_ale_rotation_readiness.py`
- `python scripts/verify_total_privacy_hardened.py`

## Rollback
- Keep previous key version active until full validation passes.
