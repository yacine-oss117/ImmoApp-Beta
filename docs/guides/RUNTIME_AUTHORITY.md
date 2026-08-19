# Runtime Authority

This document states what counts as runtime truth for the supported local
Windows workflow.

## Repo truth

The repo is authoritative for:

- source code
- migrations
- deployment manifests
- docs
- checks and supported workflows
- runtime templates and bootstrap scripts

## External local truth

The repo is not fully self-contained at runtime.

Local machine state under `C:\ProgramData\ImmoApp` is authoritative for:

- the active local env file at `C:\ProgramData\ImmoApp\config\.env.local`
- local bootstrap secret files under `C:\ProgramData\ImmoApp\secrets`
- local virtual environments
- bind-mounted Docker data
- host-local caches and persistent debug/runtime spillover

## Authority chain

For the supported Windows local runtime, the authority order is:

1. repo templates and scripts
2. `C:\ProgramData\ImmoApp\config\.env.local`
3. `C:\ProgramData\ImmoApp\secrets\...` bootstrap files
4. OpenBao live secret payload
5. Docker bind-mounted runtime data under `C:\ProgramData\ImmoApp\data\...`

Meaning:

- the repo defines how machine state is created
- ProgramData holds the actual local machine runtime inputs
- OpenBao is the normal runtime secrets authority
- Docker bind data is the local persistent service state

## Canonical local mode

The canonical supported local runtime is Docker-local with Windows bind
volumes.

Primary scripts:

- `scripts/bootstrap_local_runtime.ps1`
- `scripts/stack.ps1`
- `scripts/setup_openbao_identity.ps1`

Secondary/debug-only scripts:

- `scripts/run_server.ps1`
- `scripts/run_client.ps1`

Host-local app runtime is not the primary local truth model.

## Repo env fallback

Repo `.env` fallback is non-default and unsupported unless explicitly enabled.

If `IMMOAPP_ALLOW_REPO_ENV_FALLBACK` is not set, the supported local env file
is:

- `C:\ProgramData\ImmoApp\config\.env.local`

## Workflow state truth

Authoritative workflow state lives in:

- Postgres for leases, jobs, chunk phases, rebuild dispatch state
- object storage for importer artifacts

Cache does not own critical importer or demande rebuild workflow state.

## Health / pressure truth

Pressure truth comes from:

- Postgres health sampling
- runtime profile cache state
- short-lived tripwire overrides
- DB truth for active work counts and durable workflow records

## What is not authority

These are useful, but not authoritative:

- old notes or plan files
- one-off shell history
- local scratch files
- benchmark output files
- repo `.env` fallback files unless explicitly enabled
- Redis keys for demande rebuild queueing

If docs and code disagree, the owner docs and current code win, not old plans.
