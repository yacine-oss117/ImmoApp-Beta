# Clean Machine Bootstrap

> **Trying ImmoApp Beta?** Use the one-command [`quickstart.ps1`](../../quickstart.ps1) from the repository root. The procedure below is the manual developer/operator bootstrap and is intentionally more detailed.

Use this checklist when you cloned the repo onto a clean Windows machine and
need the supported local runtime with Docker.

This is the canonical local bootstrap path. It is the first answer to:
"What do I do first on a new machine?"

## Supported local mode

Primary local runtime:

- Docker-local stack with Windows bind volumes
- runtime state under `C:\ProgramData\ImmoApp`
- OpenBao as the normal secrets backend

Secondary local runtime:

- `scripts/run_server.ps1`
- `scripts/run_client.ps1`

Use the secondary path only for targeted host-local debugging after the machine
is already bootstrapped.

## Prerequisites

Install and verify:

- Windows machine with admin rights for `C:\ProgramData`
- Docker Desktop with Linux containers working
- Python 3.14 available as `py -3.14` or `python`
- PowerShell

Repo location:

- clone the repo
- work from the repo root

Quick checks:

```powershell
docker version
py -3.14 --version
```

If `py -3.14` is unavailable but `python --version` reports Python 3.14.x, the
bootstrap script will use that interpreter.

## Operator-supplied inputs

You must supply or confirm:

- the required operator-edit values in
  `C:\ProgramData\ImmoApp\config\.env.local`
- the local OpenBao operator username
- the local OpenBao operator password
- the secret payload written into
  `C:\ProgramData\ImmoApp\secrets\immoapp-dev-secrets.json`

The repo will generate:

- the ProgramData runtime directory tree
- the canonical env file when missing
- the server and client venvs
- `openbao.token`
- `openbao.unseal`
- `openbao-approle.json`

## Step-by-step

1. Bootstrap the declared local runtime.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_local_runtime.ps1
```

Expected result:

- `C:\ProgramData\ImmoApp\config\.env.local` exists
- `C:\ProgramData\ImmoApp\secrets\immoapp-dev-secrets.json` exists
- `C:\ProgramData\ImmoApp\venvs\immoapp-server-py314` exists
- `C:\ProgramData\ImmoApp\venvs\immoapp-client-py314` exists
- the signed-in desktop user has normal write access to host-local config/log/cache/queue paths, while local secret files retain dedicated protection

2. Edit the canonical env file.

File:

- `C:\ProgramData\ImmoApp\config\.env.local`

Replace every required placeholder reported by the bootstrap script. These are
operator-edit bootstrap values. They are not meant to stay as template
placeholders.

3. Start local infra and OpenBao bootstrap services.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-infra -UseWindowsVolumes
```

Expected result:

- `db`, `rabbitmq`, `valkey`, `minio`, `clamav`, and `openbao` are running
- `openbao-init` writes:
  - `C:\ProgramData\ImmoApp\secrets\openbao.token`
  - `C:\ProgramData\ImmoApp\secrets\openbao.unseal`

4. Create the supported OpenBao identity material.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_openbao_identity.ps1
```

Expected result:

- `C:\ProgramData\ImmoApp\secrets\openbao-approle.json` exists

5. Seed or re-seed local secrets into OpenBao.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes
```

Expected result:

- the local bootstrap JSON is loaded into OpenBao
- app services are restarted against the refreshed secret state

6. Prepare the database.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action db-prepare -UseWindowsVolumes
```

7. Start app services.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-app -UseWindowsVolumes
```

8. Verify the stack is up.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action ps -UseWindowsVolumes
```

9. Optional but recommended once per Windows profile.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/trust_local_caddy_ca.ps1
```

10. Run the desktop client.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_client.ps1
```

## Runtime checklist

At the end of bootstrap, local runtime truth should be:

- config: `C:\ProgramData\ImmoApp\config`
- secrets: `C:\ProgramData\ImmoApp\secrets`
- Docker bind data: `C:\ProgramData\ImmoApp\data`
- venvs: `C:\ProgramData\ImmoApp\venvs`
- host-local caches and tools: `C:\ProgramData\ImmoApp\cache`,
  `C:\ProgramData\ImmoApp\tools`

Docker-managed state that still lives outside ProgramData:

- `openbao_data`
- `openbao_logs`

## Supported recovery commands

- Repair a ProgramData tree created by an older elevated bootstrap:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/repair_runtime_permissions.ps1`

- Re-seed OpenBao after editing
  `C:\ProgramData\ImmoApp\secrets\immoapp-dev-secrets.json`:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes`
- Restart app services only:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action restart-app -UseWindowsVolumes`
- Reset a dirty local stack on an already bootstrapped machine:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_reset.ps1 -UseWindowsVolumes`
- Repair stale Windows bind mounts:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/fix_windows_volume_bind_mismatch.ps1 -EnvFile C:\ProgramData\ImmoApp\config\.env.local`
- Heavy infra recovery:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/infra_recover.ps1`

## Failure points

- `bootstrap_local_runtime.ps1` reports unresolved placeholders:
  edit `C:\ProgramData\ImmoApp\config\.env.local`, then continue
- `stack.ps1 -Action up-infra` fails because the env file is missing:
  run `scripts/bootstrap_local_runtime.ps1`
- `setup_openbao_identity.ps1` fails because `openbao.token` is missing:
  run `stack.ps1 -Action up-infra -UseWindowsVolumes`
- `sync-secrets` fails because the bootstrap JSON is missing:
  run `scripts/bootstrap_local_runtime.ps1`
- `sync-secrets` fails because placeholders remain in `.env.local`:
  finish editing the canonical env file, then retry

## Bootstrap vs reset

These are not the same:

- `scripts/bootstrap_local_runtime.ps1`: create declared runtime state on a
  clean or partially prepared machine
- `scripts/dev_reset.ps1`: destructive reset/recovery on an already
  bootstrapped machine

Do not use `scripts/dev_reset.ps1` as the first command on a clean machine.
