# Production Environment Matrix

Use `deployment/compose/compose.prod.yml` as an override on top of
`deployment/compose/compose.yml`:

```powershell
docker compose --project-directory . -f deployment/compose/compose.yml -f deployment/compose/compose.prod.yml up -d
```

Preferred wrapper command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-prod -EnvFile .env.prod
```

Preflight only (no containers started):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action preflight-prod -EnvFile .env.prod
```

## Required production variables

- `POSTGRES_DB`
- `POSTGRES_ADMIN_USER`
- `POSTGRES_ADMIN_PASSWORD`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `RABBITMQ_USER`
- `RABBITMQ_PASSWORD`
- `BAO_VERIFY_SSL_DOCKER=1`
- `BAO_ADDR_DOCKER` (or `BAO_ADDRS_DOCKER`) with `https://...` addresses only
- `BAO_CACERT_DOCKER` (path to CA cert inside app containers)
- `IMMOAPP_PUBLIC_BASE_URL` (public HTTPS URL)
- `DJANGO_ALLOWED_HOSTS` (must include your public hostname)
- `IMMOAPP_TLS_DOMAIN` (public hostname for Caddy/Let’s Encrypt)
- `SECURE_SSL_REDIRECT_DOCKER=1`
- `SESSION_COOKIE_SECURE_DOCKER=1`
- `CSRF_COOKIE_SECURE_DOCKER=1`

## Security expectations

- Do not rely on fallback credentials from `deployment/compose/compose.yml`.
- Keep `BAO_VERIFY_SSL=1` in all runtime services.
- Keep OpenBao addresses HTTPS-only in production (`BAO_ADDR_DOCKER` / `BAO_ADDRS_DOCKER`).
- Place OpenBao TLS material at `${IMMOAPP_OPENBAO_TLS_DIR}`:
  - `server.crt`
  - `server.key`
  - `ca.crt`
  and copy `ca.crt` to `${IMMOAPP_SECRETS_HOST_DIR}/openbao-ca.crt` for app trust.
- Keep `IMMOAPP_PUBLIC_BASE_URL` set explicitly to avoid localhost links in registration emails.
- Review warning output from:
  - `scripts/verify_prod_config.py`
  - `server.secret_store.openbao_runtime_guard`

## Strict validation gate

Enable strict checks for release pipelines:

```powershell
$env:IMMOAPP_PROD_CONFIG_STRICT = "1"
python scripts/verify_prod_config.py
```
