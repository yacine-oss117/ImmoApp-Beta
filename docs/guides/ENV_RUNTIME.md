# Runtime Map

Start here when you need one answer: what local runtime state is authoritative,
where does it live, and which script owns it.

## Canonical local runtime

The supported local runtime root is:

- `C:\ProgramData\ImmoApp`

The bootstrap owns the Windows ACL policy for this tree: the signed-in desktop user receives modify access to host-local config/log/cache/media/temp/backup/import/offline-queue paths and read/execute access to provisioned venvs. Secret files are protected separately. Older trees can be repaired with `scripts/repair_runtime_permissions.ps1`.

The primary local workflow is Docker-local with Windows bind volumes:

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_local_runtime.ps1`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-infra -UseWindowsVolumes`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_openbao_identity.ps1`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action db-prepare -UseWindowsVolumes`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-app -UseWindowsVolumes`

Host-local server/client runtime still exists, but it is secondary and
debug-only.

## Runtime inventory

| Path | Required | Type | Created/populated by | Notes |
|---|---|---|---|---|
| `C:\ProgramData\ImmoApp\config` | Yes | persistent bootstrap config | `scripts/bootstrap_local_runtime.ps1` | Canonical non-secret config root |
| `C:\ProgramData\ImmoApp\config\.env.local` | Yes | persistent bootstrap config file | `scripts/bootstrap_local_runtime.ps1` | Created from `deployment/env/.env.example`; operator edits placeholders |
| `C:\ProgramData\ImmoApp\secrets` | Yes | persistent secret/bootstrap root | `scripts/bootstrap_local_runtime.ps1` | Outside git |
| `C:\ProgramData\ImmoApp\secrets\immoapp-dev-secrets.json` | Yes | local bootstrap secret source | `scripts/bootstrap_local_runtime.ps1`, then OpenBao seed/sync | Operator-edited source for local secret sync |
| `C:\ProgramData\ImmoApp\secrets\openbao.token` | Yes | bootstrap/admin secret | `stack.ps1 -Action up-infra` via `openbao-init` | OpenBao admin/root token file; not the normal app runtime identity |
| `C:\ProgramData\ImmoApp\secrets\openbao.unseal` | Yes | bootstrap secret | `stack.ps1 -Action up-infra` via `openbao-init` | OpenBao unseal key |
| `C:\ProgramData\ImmoApp\secrets\openbao-approle.json` | Yes | app runtime identity secret | `scripts/setup_openbao_identity.ps1` or `openbao-seed` | AppRole credentials used by runtime |
| `C:\ProgramData\ImmoApp\data\pgdata` | Yes | persistent Docker bind data | bootstrap creates, Postgres populates | PostgreSQL data directory |
| `C:\ProgramData\ImmoApp\data\rabbitmq` | Yes | persistent Docker bind data | bootstrap creates, RabbitMQ populates | RabbitMQ data |
| `C:\ProgramData\ImmoApp\data\valkey` | Yes | persistent Docker bind data | bootstrap creates, Valkey populates | Valkey data |
| `C:\ProgramData\ImmoApp\data\minio` | Yes | persistent Docker bind data | bootstrap creates, MinIO populates | Object storage data |
| `C:\ProgramData\ImmoApp\data\clamav` | Yes | persistent Docker bind data | bootstrap creates, ClamAV populates | Virus definition data |
| `C:\ProgramData\ImmoApp\data\caddy\data` | Yes | persistent Docker bind data | bootstrap creates, Caddy populates | Caddy runtime data |
| `C:\ProgramData\ImmoApp\data\caddy\config` | Yes | persistent Docker bind data | bootstrap creates, Caddy populates | Caddy runtime config |
| `C:\ProgramData\ImmoApp\data\app` | Yes | persistent Docker bind root | bootstrap creates | Mounted into Docker app containers as `/var/lib/immoapp` |
| `C:\ProgramData\ImmoApp\data\app\cache` | Yes | Docker app cache | `scripts/bootstrap_local_runtime.ps1` | Docker app cache subtree |
| `C:\ProgramData\ImmoApp\data\app\media` | Yes | Docker app persistent data | `scripts/bootstrap_local_runtime.ps1` | Docker app media subtree |
| `C:\ProgramData\ImmoApp\data\app\static` | Yes | Docker app persistent data | `scripts/bootstrap_local_runtime.ps1` | Django static root for Docker app runtime |
| `C:\ProgramData\ImmoApp\data\app\logs` | Yes | Docker app persistent data | `scripts/bootstrap_local_runtime.ps1` | Docker app log subtree |
| `C:\ProgramData\ImmoApp\data\app\backups` | Yes | Docker app persistent data | `scripts/bootstrap_local_runtime.ps1` | Docker app backup subtree |
| `C:\ProgramData\ImmoApp\data\app\config` | Yes | Docker app persistent data | `scripts/bootstrap_local_runtime.ps1` | Docker app config subtree |
| `C:\ProgramData\ImmoApp\data\app\tools` | Yes | Docker app cache/tool data | `scripts/bootstrap_local_runtime.ps1` | Docker app tool subtree |
| `C:\ProgramData\ImmoApp\data\app\tmp` | Yes | Docker app temp data | `scripts/bootstrap_local_runtime.ps1` | Docker app temp subtree |
| `C:\ProgramData\ImmoApp\venvs\immoapp-server-py314` | Yes | generated persistent runtime toolchain | `scripts/bootstrap_local_runtime.ps1` | Host-local server/checks Python venv |
| `C:\ProgramData\ImmoApp\venvs\immoapp-client-py314` | Yes | generated persistent runtime toolchain | `scripts/bootstrap_local_runtime.ps1` | Host-local client Python venv |
| `C:\ProgramData\ImmoApp\cache` | Optional but supported | host-local cache | bootstrap creates, host runtime populates | Includes pycache and UI cache artifacts |
| `C:\ProgramData\ImmoApp\tools` | Optional but supported | host-local tool cache | bootstrap creates, host runtime/checks populate | Ruff, pytest, mypy, coverage data |
| `C:\ProgramData\ImmoApp\logs` | Optional but supported | host-local persistent data | bootstrap creates, host runtime populates | Host-local logs and onboarding events |
| `C:\ProgramData\ImmoApp\media` | Optional but supported | host-local persistent data | bootstrap creates, host runtime populates | Host-local media path |
| `C:\ProgramData\ImmoApp\tmp` | Optional but supported | host-local temp data | bootstrap creates, host runtime populates | Safe to clear when not in use |
| `C:\ProgramData\ImmoApp\backups` | Optional but supported | host-local persistent data | bootstrap creates, runtime/recovery scripts populate | Recovery backups and manual backups |
| `C:\ProgramData\ImmoApp\offline_sync` | Optional but supported | host-local persistent data | bootstrap creates, desktop runtime populates | Account-scoped offline sync state |
| `C:\ProgramData\ImmoApp\api_write_queue` | Optional but supported | host-local persistent data | bootstrap creates, desktop runtime populates | Local resilient API mutation queue |
| `C:\ProgramData\ImmoApp\imports` | Optional but supported | host-local persistent data | bootstrap creates, runtime populates | Import/runtime spillover area |

## Runtime paths outside ProgramData

The canonical external runtime root is still `C:\ProgramData\ImmoApp`.

The local Docker workflow has two important named volumes that are not mapped
into that tree:

- `openbao_data`
- `openbao_logs`

Those remain Docker-managed local state. They are part of the supported local
runtime, but they are not hidden tribal knowledge anymore.

## Primary vs secondary local modes

### Docker-local stack runtime

This is the primary supported local runtime.

Authority:

- env bootstrap file: `C:\ProgramData\ImmoApp\config\.env.local`
- local bootstrap files: `C:\ProgramData\ImmoApp\secrets\...`
- runtime secrets: OpenBao
- persistent Docker data: `C:\ProgramData\ImmoApp\data\...`
- local HTTPS endpoint: `https://localhost`

Use:

- `scripts/bootstrap_local_runtime.ps1`
- `scripts/stack.ps1`
- `scripts/setup_openbao_identity.ps1`

### Host-local app runtime

Use only when debugging Django and/or the desktop client directly on Windows.

Authority:

- env bootstrap file: `C:\ProgramData\ImmoApp\config\.env.local`
- runtime secrets: OpenBao
- host-local persistent state: top-level `cache`, `tools`, `logs`, `media`,
  `tmp`, `backups`, `offline_sync`, `api_write_queue`, `imports`

Use:

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_server.ps1`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_client.ps1`

This path is explicitly secondary and debug-only.

## Env resolution order

1. `DJANGO_ENV_FILE` if explicitly set
2. `C:\ProgramData\ImmoApp\config\.env.local`
3. repo fallback only when `IMMOAPP_ALLOW_REPO_ENV_FALLBACK=1`

If you are relying on repo `.env` files without that flag, you are off the
supported path.

## Secrets flow summary

- Keep non-secret bootstrap/runtime config in `.env.local`.
- Keep real runtime secrets in OpenBao.
- Keep local bootstrap secret material under `C:\ProgramData\ImmoApp\secrets`.
- Editing `immoapp-dev-secrets.json` does not update live runtime by itself.
- After editing that file, use:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes`

## Bootstrap-only vs OpenBao-owned values

Treat these as bootstrap/runtime config that stays in `.env.local`:

- `POSTGRES_*`
- `RABBITMQ_*`
- `MINIO_*`
- `STORAGE_ENDPOINT_URL`, `STORAGE_BUCKET`, and related non-secret storage config
- `BAO_*`
- runtime endpoint and policy values such as `IMMOAPP_PUBLIC_BASE_URL`,
  `DJANGO_ALLOWED_HOSTS`, `OTEL_*`, `SIGNOZ_*`

Treat these as OpenBao-owned runtime secrets in normal local mode:

- `DJANGO_SECRET_KEY`
- `ALE_MASTER_KEY`
- `ALE_SEARCH_SECRET`
- `ALE_KDF_SALT`
- any other real application secret carried through the local bootstrap JSON and
  synced into OpenBao

Do not rely on plaintext repo or ProgramData env secrets as the normal runtime
source when OpenBao mode is enabled.

## First commands on a clean machine

The canonical answer to "I just cloned the repo, what do I do first?" is:

- [CLEAN_MACHINE_BOOTSTRAP.md](CLEAN_MACHINE_BOOTSTRAP.md)

That checklist is the authoritative bootstrap path.
