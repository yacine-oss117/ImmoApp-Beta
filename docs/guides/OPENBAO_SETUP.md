# OpenBao Setup

This document explains the supported local OpenBao bootstrap and runtime flow.
It is part of the canonical Docker-local bootstrap path.

## Runtime policy

Normal local runtime policy:

- `IMMOAPP_SECRETS_BACKEND=openbao`
- `IMMOAPP_SECRETS_REQUIRED=1`
- `IMMOAPP_ALLOW_ENV_SECRETS=0`
- `BAO_TOKEN` stays empty in normal runtime
- runtime services use AppRole, not a long-lived admin token

Keep bootstrap config in `C:\ProgramData\ImmoApp\config\.env.local`.
Keep real runtime secrets in OpenBao.

## File glossary

- `C:\ProgramData\ImmoApp\secrets\openbao.token`
  OpenBao admin/root token written by `openbao-init`. This is for bootstrap and
  admin actions, not the normal app runtime identity.
- `C:\ProgramData\ImmoApp\secrets\openbao.unseal`
  OpenBao unseal key written by `openbao-init`.
- `C:\ProgramData\ImmoApp\secrets\openbao-approle.json`
  Generated AppRole credentials for the application runtime. This is the normal
  local runtime identity consumed through `BAO_APPROLE_FILE`.
- `C:\ProgramData\ImmoApp\secrets\immoapp-dev-secrets.json`
  Canonical local bootstrap secret source. This file is the operator-edited
  payload that `sync-secrets` loads into OpenBao.

## Supported order

1. `scripts/bootstrap_local_runtime.ps1`
2. edit `C:\ProgramData\ImmoApp\config\.env.local`
3. `scripts/stack.ps1 -Action up-infra -UseWindowsVolumes`
4. `scripts/setup_openbao_identity.ps1`
5. `scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes`
6. `scripts/stack.ps1 -Action db-prepare -UseWindowsVolumes`
7. `scripts/stack.ps1 -Action up-app -UseWindowsVolumes`

That is the supported local OpenBao bootstrap path. Do not replace it with ad
hoc manual copying or a different script order.

## What each step does

`scripts/bootstrap_local_runtime.ps1`:

- creates the declared `C:\ProgramData\ImmoApp` runtime layout
- creates `C:\ProgramData\ImmoApp\config\.env.local` from
  `deployment/env/.env.example` when missing
- creates `C:\ProgramData\ImmoApp\secrets\immoapp-dev-secrets.json` as an empty
  JSON object when missing
- creates or syncs the server and client venvs

`scripts/stack.ps1 -Action up-infra -UseWindowsVolumes`:

- starts db/rabbitmq/valkey/minio/clamav/openbao
- runs `openbao-init`
- runs `openbao-seed`
- writes `openbao.token`
- writes `openbao.unseal`

`scripts/setup_openbao_identity.ps1`:

- requires the canonical env file
- requires the server venv
- requires `openbao.token`
- requires a reachable local OpenBao instance
- creates or refreshes the operator identity, app policy, AppRole, and
  `openbao-approle.json`

`scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes`:

- validates `immoapp-dev-secrets.json`
- seeds or re-seeds the configured OpenBao secret path from that local JSON
- refreshes app services against the updated secret state

## Persisted locally vs loaded into OpenBao

Persisted locally under `C:\ProgramData\ImmoApp`:

- `.env.local`
- `immoapp-dev-secrets.json`
- `openbao.token`
- `openbao.unseal`
- `openbao-approle.json`

Loaded into OpenBao:

- application secrets such as `DJANGO_SECRET_KEY`
- encryption/materialization secrets such as `ALE_*`
- local runtime secrets that the stack hydrates from OpenBao for containers

Important rule:

- editing `immoapp-dev-secrets.json` does not change live runtime by itself
- after editing it, run
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes`

## What the operator must supply

The operator must supply or confirm:

- required operator-edit values in `.env.local`
- OpenBao operator username
- OpenBao operator password
- the desired local secret payload in `immoapp-dev-secrets.json`

The repo-generated parts are:

- directory structure
- env template instantiation
- venvs
- OpenBao token/unseal files
- AppRole file

## Addressing

For local Windows host-side bootstrap:

- `BAO_ADDR` should point to the host-reachable local address
- the env template defaults it to `http://127.0.0.1:8200`

For Docker container runtime:

- `BAO_ADDR_DOCKER=http://openbao:8200`

Use `BAO_ADDRS` or `BAO_ADDRS_DOCKER` only when the deployment actually needs
multiple OpenBao nodes.

## Failure handling

Supported failure messages should point you back to the correct order:

- missing env file: run `scripts/bootstrap_local_runtime.ps1`
- missing `openbao.token`: run `stack.ps1 -Action up-infra -UseWindowsVolumes`
- unreachable OpenBao: run `stack.ps1 -Action up-infra -UseWindowsVolumes`
- missing AppRole file during runtime: run `scripts/setup_openbao_identity.ps1`
- stale or changed local bootstrap secret payload: run
  `stack.ps1 -Action sync-secrets -UseWindowsVolumes`

## Verification helpers

- `C:\ProgramData\ImmoApp\venvs\immoapp-server-py314\Scripts\python.exe scripts/verify_openbao_runtime_env.py`
- `C:\ProgramData\ImmoApp\venvs\immoapp-server-py314\Scripts\python.exe scripts/verify_openbao_ha_readiness.py`

## Local note

For browser-clean local HTTPS in stack mode, trust the local Caddy CA once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/trust_local_caddy_ca.ps1
```
