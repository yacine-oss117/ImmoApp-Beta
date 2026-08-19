$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$script:ImmoAppBlackTargets = @(
    "app",
    "core",
    "server",
    "tests",
    "scripts"
)
$script:ImmoAppRuffTargets = @(
    "app",
    "server",
    "core"
)
$script:ImmoAppMypyTargets = @(
    "app",
    "core",
    "server"
)

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Script
    )
    $startedAt = Get-Date
    Write-Host ("[STEP] {0} (start {1})" -f $Name, $startedAt.ToString("HH:mm:ss")) -ForegroundColor DarkGray
    & $Script
    $duration = (Get-Date) - $startedAt
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE after $([math]::Round($duration.TotalSeconds, 2))s"
    }
    Write-Host ("[STEP] {0} completed in {1}s" -f $Name, [math]::Round($duration.TotalSeconds, 2)) -ForegroundColor DarkGray
}

function Initialize-ImmoAppChecksContext {
    $paths = Ensure-ImmoAppTools
    Set-ImmoAppCacheEnv -Paths $paths
    Set-ImmoAppSecurityEnv
    Import-ImmoAppEnvFile
    Set-ImmoAppEnvFromBootstrapSecrets -Names @(
        "DJANGO_SECRET_KEY",
        "ALE_KEY_VERSION",
        "ALE_MASTER_KEY",
        "ALE_SEARCH_SECRET",
        "ALE_KDF_SALT",
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

    $serverPython = Get-ImmoAppVenvPython -Kind server
    if (-not (Test-Path $serverPython)) {
        throw "Server venv python not found at $serverPython"
    }

    $clientPython = Get-ImmoAppVenvPython -Kind client
    if (-not (Test-Path $clientPython)) {
        throw "Client venv python not found at $clientPython"
    }

    return @{
        Paths = $paths
        ServerPython = $serverPython
        ClientPython = $clientPython
    }
}

function Invoke-LintChecks {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Context
    )

    $serverPython = $Context.ServerPython
    $pycache = $Context.Paths.Pycache

    Invoke-External "black --check" {
        & $serverPython -X pycache_prefix=$pycache -m black --check @script:ImmoAppBlackTargets
    }
    Invoke-External "ruff check" {
        & $serverPython -X pycache_prefix=$pycache -m ruff check @script:ImmoAppRuffTargets
    }
}

function Invoke-TypeChecks {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Context
    )

    $serverPython = $Context.ServerPython
    $pycache = $Context.Paths.Pycache
    foreach ($target in $script:ImmoAppMypyTargets) {
        Invoke-External "mypy $target" {
            & $serverPython -X pycache_prefix=$pycache -m mypy $target
        }
    }
}

function Invoke-DjangoModelDriftCheck {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Context
    )

    $serverPython = $Context.ServerPython
    Invoke-External "django model drift check (makemigrations --check --dry-run)" {
        $origSecretsBackend = $env:IMMOAPP_SECRETS_BACKEND
        $origAllowEnvSecrets = $env:IMMOAPP_ALLOW_ENV_SECRETS
        $origSecretsRequired = $env:IMMOAPP_SECRETS_REQUIRED
        $origSecretsOverwrite = $env:IMMOAPP_SECRETS_OVERWRITE
        $origImmoAppEnv = $env:IMMOAPP_ENV
        $origSkipCelery = $env:IMMOAPP_SKIP_CELERY_APP
        $origSkipAsgiFallback = $env:IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK
        $origDjangoSecretKey = $env:DJANGO_SECRET_KEY
        $origDjangoDebug = $env:DJANGO_DEBUG
        $origDjangoAllowedHosts = $env:DJANGO_ALLOWED_HOSTS
        $origCeleryBrokerUrl = $env:CELERY_BROKER_URL
        $origPostgresHost = $env:POSTGRES_HOST
        $origPostgresPort = $env:POSTGRES_PORT
        $origPostgresDb = $env:POSTGRES_DB
        $origPostgresUser = $env:POSTGRES_USER
        $origPostgresPassword = $env:POSTGRES_PASSWORD
        $origPostgresAdminUser = $env:POSTGRES_ADMIN_USER
        $origPostgresAdminPassword = $env:POSTGRES_ADMIN_PASSWORD
        $origPgConnectTimeout = $env:PGCONNECT_TIMEOUT
        try {
            # Drift check should validate model state, not runtime secret backends.
            # Force lightweight env-only bootstrap so this step stays fast/offline.
            $env:IMMOAPP_SECRETS_BACKEND = "env"
            $env:IMMOAPP_ALLOW_ENV_SECRETS = "1"
            $env:IMMOAPP_SECRETS_REQUIRED = "0"
            $env:IMMOAPP_SECRETS_OVERWRITE = "0"
            $env:IMMOAPP_ENV = "ci"
            $env:IMMOAPP_SKIP_CELERY_APP = "1"
            $env:IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK = "1"
            $env:DJANGO_SECRET_KEY = "check-django-secret-key-unsafe-for-prod"
            $env:DJANGO_DEBUG = "1"
            $env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1"
            $env:CELERY_BROKER_URL = "amqp://immoapp:immoapp@localhost:5672//"
            $env:POSTGRES_HOST = "127.0.0.1"
            $env:POSTGRES_PORT = "5432"
            $env:POSTGRES_DB = "immoapp"
            $env:POSTGRES_USER = "immoapp_app"
            $env:POSTGRES_PASSWORD = "immoapp_app_password"
            $env:POSTGRES_ADMIN_USER = "immoapp"
            $env:POSTGRES_ADMIN_PASSWORD = "immoapp_admin_password"
            $env:PGCONNECT_TIMEOUT = "5"
            & $serverPython server/manage.py makemigrations --check --dry-run
        }
        finally {
            $env:IMMOAPP_SECRETS_BACKEND = $origSecretsBackend
            $env:IMMOAPP_ALLOW_ENV_SECRETS = $origAllowEnvSecrets
            $env:IMMOAPP_SECRETS_REQUIRED = $origSecretsRequired
            $env:IMMOAPP_SECRETS_OVERWRITE = $origSecretsOverwrite
            $env:IMMOAPP_ENV = $origImmoAppEnv
            $env:IMMOAPP_SKIP_CELERY_APP = $origSkipCelery
            $env:IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK = $origSkipAsgiFallback
            $env:DJANGO_SECRET_KEY = $origDjangoSecretKey
            $env:DJANGO_DEBUG = $origDjangoDebug
            $env:DJANGO_ALLOWED_HOSTS = $origDjangoAllowedHosts
            $env:CELERY_BROKER_URL = $origCeleryBrokerUrl
            $env:POSTGRES_HOST = $origPostgresHost
            $env:POSTGRES_PORT = $origPostgresPort
            $env:POSTGRES_DB = $origPostgresDb
            $env:POSTGRES_USER = $origPostgresUser
            $env:POSTGRES_PASSWORD = $origPostgresPassword
            $env:POSTGRES_ADMIN_USER = $origPostgresAdminUser
            $env:POSTGRES_ADMIN_PASSWORD = $origPostgresAdminPassword
            $env:PGCONNECT_TIMEOUT = $origPgConnectTimeout
        }
    }
}
