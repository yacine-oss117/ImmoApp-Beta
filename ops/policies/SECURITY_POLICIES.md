**Security Policies (Production Grade)**

**ALE Key Rotation**
- **Cadence:** rotate every 6 months or immediately after any key leak.
- **Active Keys:** keep **current + previous** in `ALE_MASTER_KEYS`.
- **Rotation Steps:**
  1. Generate new key `vN`, set `ALE_KEY_VERSION=vN` and include both keys in `ALE_MASTER_KEYS`.
  2. Run `scripts/rotate_ale_keys.py` to re-encrypt all ciphertext to the new key.
  3. Verify: `scripts/verify_total_privacy_hardened.py`.
  4. Remove old key from `ALE_MASTER_KEYS` after verification.

**Search Secret Rotation (DB-Native Hashing)**
- **Cadence:** rotate with key rotation or if search secret is compromised.
- **Requirement:** `ALE_SEARCH_SECRET_MASTER` (or `ALE_SEARCH_SECRET`) is mandatory (**fail-secure**).
- **Rotation Steps:**
  1. Start version window: `python scripts/rotate_ale_search_keys.py --start vN`.
  2. Reindex search hashes: `python scripts/reindex_ale_search.py --force`.
  3. Finalize window: `python scripts/rotate_ale_search_keys.py --finalize`.
  4. Verify: `python scripts/verify_ale_rotation_readiness.py`.
- **Zero-downtime behavior:** during rotation, sessions use both current + previous versions.

**KDF Salt Policy**
- **Requirement:** `ALE_KDF_SALT` is mandatory and must be at least 16 characters.
- **Rationale:** prevents predictable key-derivation output across environments.

**PII Retention**
- **Policy:** purge encrypted PII for **soft-deleted** rows after 365 days.
- **Config:** `ALE_PII_RETENTION_DAYS` (default `365`).
- **Job:** schedule `scripts/purge_ale_pii.py` daily/weekly in production.

**Rotation Alerts & Readiness**
- Daily Celery task `ale_rotation_alert_task` notifies owners when key/pepper rotations are overdue.
- CI/ops gate uses `scripts/verify_ale_rotation_readiness.py` to fail builds if rotation is overdue.

**Optional Auto-Rotation (Disabled by Default)**
- `ALE_AUTOROTATE_ENABLED=1` enables the scheduled `rotate_ale_keys_task`.
- `ALE_AUTOREINDEX_ENABLED=1` enables the scheduled `reindex_ale_search_task`.
- Defaults are **off** for safety; keep manual control in production.

**Secret Management**
- **Minimum:** environment variables injected by the host (Docker/K8s secrets).
- **Recommended:** OS secret store or KMS (Vault/Keyring/AWS KMS/Azure Key Vault).
- **Local runtime config policy:** use `C:\ProgramData\ImmoApp\config\.env.local` only (or set `DJANGO_ENV_FILE` explicitly).
- **Never:** commit keys to `.env`/`.env.local` or store secrets in client-side code.
- CI enforces this with `scripts/verify_no_secrets.py` in enforcement mode.

**Logging Boundaries**
- Log **only** key version + operation timing.
- **Never** log PII, ciphertext, or masked plaintext.
- Keep ALE audit scripts for verification, not logging data.

**Backups**
- Encrypted DB backups are **still required**.
- Keep backup retention shorter than the PII retention window unless compliance requires more.
