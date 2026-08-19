# KMS + ALE Rotation Runbook (Production-Safe)

This is the **one‑page checklist** for encrypting object storage (MinIO/S3) and rotating ALE keys **without data loss**.

## Part A — MinIO KMS (Object Storage Encryption)

### 1) Configure KMS secret
Set a KMS key in your environment (never hardcode it in git).

```
MINIO_KMS_SECRET_KEY=immoapp-kms-key:<32+ chars secret>
```

### 2) Enable SSE‑KMS for uploads
In your app env:

```
STORAGE_SSE=aws:kms
STORAGE_SSE_KMS_KEY_ID=immoapp-kms-key
```

### 3) Restart MinIO
MinIO only reads KMS settings on boot.

```
docker compose --project-directory . -f deployment/compose/compose.yml up -d minio minio-init
```

### 4) Verify
Upload a file and confirm headers include:
```
x-amz-server-side-encryption: aws:kms
```

---

## Part B — ALE Key Rotation (PII encryption)

### ✅ Golden Rules
- **Never delete old keys** until all data is re‑encrypted.
- If you lose a key, **old data is permanently unreadable**.
- Rotation is **manual unless explicitly enabled**.

### 1) Add the new key (keep old key)
Example (v1 → v2):
```
ALE_MASTER_KEY_V1=old_key
ALE_MASTER_KEY_V2=new_key
ALE_KEY_VERSION=v2
```

### 2) Deploy + restart app
New encryptions now use v2. Old data still decrypts via v1.

### 3) Re‑encrypt existing data
Run rotation task:
```
ALE_AUTOROTATE_ENABLED=1
```
Then run:
```
python -m server.api.tasks rotate_ale_keys_task
```

### 4) Rebuild search indexes (if needed)
```
ALE_AUTOREINDEX_ENABLED=1
python -m server.api.tasks reindex_ale_search_task
```

### 5) Verify
Run your privacy audit (verify_total_privacy_zero.py or checks.ps1).

### 6) Remove old key
Only after the audit confirms **all rows are encrypted with v2**.

---

## Part C — ALE Search-Key Rotation (Versioned, Zero-Downtime)

Search-key rotation is now explicit and versioned via metadata:
- `ale_search_key_version` (current)
- `ale_search_key_prev_version` (optional during transition)

During transition, DB sessions inject both secrets (`current + previous`), so search
keeps working while reindex runs.

### 1) Start rotation window
```
python scripts/rotate_ale_search_keys.py --start v2
```

### 2) Reindex search columns
```
python scripts/reindex_ale_search.py
```

### 3) Finalize rotation window
```
python scripts/rotate_ale_search_keys.py --finalize
```

### 4) Verify readiness
```
python scripts/verify_ale_rotation_readiness.py
```

Notes:
- Existing `v1` derivation remains backward-compatible.
- `v2+` derivation is version-scoped.
- Keep `ALE_SEARCH_SECRET_MASTER` stable; rotate by version metadata + reindex.

---

## Production Recommendation

- Store ALE keys in **Vault / AWS Secrets Manager / Azure Key Vault**
- Rotate keys every 90–180 days
- Keep rotation **manual + audited**
