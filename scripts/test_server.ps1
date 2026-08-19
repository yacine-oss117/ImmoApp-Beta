param(
    [string]$PytestTarget = "app/tests/server_tests",
    [string]$PytestMarker = "",
    [switch]$SkipDjangoFirewall,
    [switch]$RunConnectionLeakTests
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
Set-ImmoAppSecurityEnv
Import-ImmoAppEnvFile
Set-ImmoAppHostRuntimeEndpoints

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Script
    )
    & $Script
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Initialize-ServerTestEnv {
    Set-ImmoAppEnvFromBootstrapSecrets -Names @(
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_ADMIN_USER",
        "POSTGRES_ADMIN_PASSWORD",
        "RABBITMQ_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "STORAGE_SECRET_KEY",
        "CELERY_BROKER_URL"
    )

    # Host-side tests target Docker-published Postgres on localhost.
    if (-not $env:POSTGRES_HOST -or $env:POSTGRES_HOST -eq "db") {
        $env:POSTGRES_HOST = "127.0.0.1"
    }
    if (-not $env:POSTGRES_PORT) {
        $env:POSTGRES_PORT = "5432"
    }
    if (-not $env:POSTGRES_DB) {
        $env:POSTGRES_DB = "immoapp"
    }
    if (-not $env:POSTGRES_USER) {
        $env:POSTGRES_USER = "immoapp_app"
    }
    if (-not $env:POSTGRES_PASSWORD) {
        $env:POSTGRES_PASSWORD = "immoapp_app_password"
    }
    if (-not $env:POSTGRES_ADMIN_USER) {
        $env:POSTGRES_ADMIN_USER = "immoapp"
    }
    if (-not $env:POSTGRES_ADMIN_PASSWORD) {
        $env:POSTGRES_ADMIN_PASSWORD = "immoapp_admin_password"
    }
    if (-not $env:DJANGO_SETTINGS_MODULE) {
        $env:DJANGO_SETTINGS_MODULE = "server.immoapp_server.settings"
    }
    $env:IMMOAPP_ENV = "ci"
    if (-not $env:DJANGO_DEBUG) {
        $env:DJANGO_DEBUG = "1"
    }
    if (-not $env:DJANGO_ALLOWED_HOSTS) {
        $env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1"
    }
    if (-not $env:DJANGO_SECRET_KEY) {
        $env:DJANGO_SECRET_KEY = "test-django-secret-key-unsafe-for-prod"
    }
    if (-not $env:PGCONNECT_TIMEOUT) {
        $env:PGCONNECT_TIMEOUT = "5"
    }

    # Host-resolvable runtime endpoints for integration tests.
    $env:VALKEY_URL = "redis://127.0.0.1:6379/1"
    $env:CHANNEL_LAYER_URL = "redis://127.0.0.1:6379/2"
    $env:STORAGE_ENDPOINT_URL = "http://127.0.0.1:9000"
    if (-not $env:ALE_KEY_VERSION) {
        $env:ALE_KEY_VERSION = "v1"
    }
    if (-not $env:ALE_MASTER_KEY) {
        $env:ALE_MASTER_KEY = "test-master-key-32-bytes-minimum"
    }
    if (-not $env:ALE_SEARCH_SECRET) {
        $env:ALE_SEARCH_SECRET = "test-search-secret"
    }
    if (-not $env:ALE_KDF_SALT) {
        $env:ALE_KDF_SALT = "test-kdf-salt-123456"
    }

    # Server tests run on host; keep OpenBao loads focused on app/runtime keys
    # while DB coordinates are sourced from explicit test env above.
    $env:IMMOAPP_ALLOW_ENV_SECRETS = "1"
    $env:IMMOAPP_SECRETS_ALLOWLIST = "ALE_,DJANGO_,IMMOAPP_,RABBITMQ_,CELERY_BROKER_URL,VALKEY_URL,CHANNEL_LAYER_URL,MINIO_,STORAGE_,SIGNOZ_,JWT_"
    $env:IMMOAPP_SECRETS_OVERWRITE = "0"
    $env:IMMOAPP_SECRETS_REQUIRED = "0"
    $env:IMMOAPP_SECRETS_BACKEND = "env"
    $env:PYTHONPATH = "."
}

function Assert-PostgresEndpointReachable {
    $pgHost = $env:POSTGRES_HOST
    $port = 5432
    try {
        $port = [int]$env:POSTGRES_PORT
    }
    catch {
        $port = 5432
    }
    if ([string]::IsNullOrWhiteSpace($pgHost)) {
        $pgHost = "127.0.0.1"
    }

    $reachable = Test-NetConnection -ComputerName $pgHost -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
    if (-not $reachable) {
        throw "Postgres endpoint is not reachable at ${pgHost}:${port}. Start infra first (scripts/stack.ps1 -Action up-infra)."
    }
}

$serverPython = Get-ImmoAppVenvPython -Kind server
if (-not (Test-Path $serverPython)) {
    throw "Server venv python not found at $serverPython"
}
Initialize-ServerTestEnv
Assert-PostgresEndpointReachable
Invoke-Step "Django migrate (accounts/auth schema sync)" {
    $origUser = $env:POSTGRES_USER
    $origPass = $env:POSTGRES_PASSWORD
    if ($env:POSTGRES_ADMIN_USER) {
        $env:POSTGRES_USER = $env:POSTGRES_ADMIN_USER
    }
    if ($env:POSTGRES_ADMIN_PASSWORD) {
        $env:POSTGRES_PASSWORD = $env:POSTGRES_ADMIN_PASSWORD
    }
    try {
        & $serverPython server/manage.py migrate --noinput
    }
    finally {
        $env:POSTGRES_USER = $origUser
        $env:POSTGRES_PASSWORD = $origPass
    }
}

$pytestArgs = @($PytestTarget)
if ($PytestMarker) {
    $pytestArgs += @("-m", $PytestMarker)
}
Invoke-Step "pytest $PytestTarget" { & $serverPython -m pytest @pytestArgs }

if (-not $SkipDjangoFirewall) {
    Invoke-Step "Django firewall tests" {
        & $serverPython server/manage.py test server.api.tests.test_firewall --noinput
    }
}

if ($RunConnectionLeakTests) {
    Invoke-Step "pytest tests/backend/test_connection_leak.py" {
        & $serverPython -m pytest tests/backend/test_connection_leak.py -v
    }
}
