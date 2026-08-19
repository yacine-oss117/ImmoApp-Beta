# Deployment Assets

This directory is the single home for deployment and bootstrap manifests.

## Ownership

- `compose/`: Docker Compose manifests and overlays
- `docker/`: Dockerfile, container entrypoints, init scripts, OpenBao config,
  SigNoz assets
- `proxy/`: Caddy configs
- `env/`: env templates only

## Rules

- Human-facing workflow commands stay in `scripts/` and `Makefile`.
- Runtime documentation stays in `docs/guides/`.
- Operational runbooks and policies stay in `ops/`.
- Do not put ad hoc notes, scratch files, or exported logs under `deployment/`.

## Direct Compose Usage

Prefer:

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 ...`
- `make up`, `make down`, `make up-full`

If you need raw compose commands from repo root, keep `--project-directory .`
and use the files under `deployment/compose/`, for example:

```powershell
docker compose --project-directory . -f deployment/compose/compose.yml -f deployment/compose/compose.windows.yml up -d
```

## Env Templates

`deployment/env/` contains templates only. Real runtime env files stay outside
the repo, normally under `C:\ProgramData\ImmoApp\config\`.
