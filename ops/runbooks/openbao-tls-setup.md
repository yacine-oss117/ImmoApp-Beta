# OpenBao TLS Setup (Production)

This runbook configures TLS for the in-stack OpenBao service used by
`deployment/compose/compose.prod.yml`.

## 1) Generate internal CA and OpenBao server cert

Use a host with OpenSSL available:

```powershell
$tlsDir = "C:\ProgramData\ImmoApp\secrets\openbao\tls"
New-Item -ItemType Directory -Force -Path $tlsDir | Out-Null
Push-Location $tlsDir

openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=ImmoApp OpenBao CA"

openssl genrsa -out server.key 4096
@"
[req]
default_bits = 4096
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = openbao

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = openbao
DNS.2 = localhost
"@ | Set-Content -Path .\server-openssl.cnf -Encoding UTF8

openssl req -new -key server.key -out server.csr -config .\server-openssl.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 825 -sha256 -extensions req_ext -extfile .\server-openssl.cnf

Pop-Location
Copy-Item "$tlsDir\ca.crt" "C:\ProgramData\ImmoApp\secrets\openbao-ca.crt" -Force
```

## 2) Set production env values

In `.env.prod`:

- `BAO_ADDR_DOCKER=https://openbao:8200`
- `BAO_VERIFY_SSL_DOCKER=1`
- `BAO_CACERT_DOCKER=/run/immoapp-secrets/openbao-ca.crt`
- `IMMOAPP_OPENBAO_TLS_DIR=C:/ProgramData/ImmoApp/secrets/openbao/tls`

## 3) Validate and start

```powershell
$env:IMMOAPP_PROD_CONFIG_STRICT = "1"
python scripts/verify_prod_config.py
powershell -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action preflight-prod -EnvFile .env.prod
powershell -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-prod -EnvFile .env.prod
```

## 4) Verify OpenBao TLS is active

```powershell
docker compose --project-directory . -f deployment/compose/compose.yml -f deployment/compose/compose.prod.yml exec -T openbao sh -lc "bao status -address=https://openbao:8200 -ca-cert=/openbao/tls/ca.crt"
```

Expected:
- `Initialized true`
- `Sealed false`
- No TLS verification errors
