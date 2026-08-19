param(
    [Parameter(Mandatory = $true)]
    [string]$EnvFile
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
    throw "Env file not found: $EnvFile"
}

function Get-EnvValueFromFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    foreach ($rawLine in Get-Content $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { continue }
        $key = $line.Substring(0, $eq).Trim()
        if ($key -ne $Name) { continue }
        $value = $line.Substring($eq + 1).Trim()
        if (
            ($value.StartsWith("'") -and $value.EndsWith("'")) -or
            ($value.StartsWith('"') -and $value.EndsWith('"'))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        return $value
    }
    return ""
}

function Require-Env {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$InvalidValue = ""
    )
    $value = Get-EnvValueFromFile -Path $EnvFile -Name $Name
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required env var: $Name"
    }
    if ($InvalidValue -and $value -eq $InvalidValue) {
        throw "Env var $Name uses forbidden default value."
    }
    if ($value -like "REPLACE_WITH*") {
        throw "Env var $Name still contains placeholder value."
    }
    return $value
}

function Require-FlagOne {
    param([Parameter(Mandatory = $true)][string]$Name)
    $value = Get-EnvValueFromFile -Path $EnvFile -Name $Name
    if ($value -ne "1") {
        throw "$Name must be set to 1 in production env file."
    }
}

function Require-FlagZero {
    param([Parameter(Mandatory = $true)][string]$Name)
    $value = Get-EnvValueFromFile -Path $EnvFile -Name $Name
    if ([string]::IsNullOrWhiteSpace($value)) {
        return
    }
    if ($value -ne "0") {
        throw "$Name must be unset or set to 0 in production env file."
    }
}

Write-Host "[preflight-prod] validating env file: $EnvFile" -ForegroundColor Cyan

Require-FlagZero -Name "DJANGO_DEBUG"
Require-FlagZero -Name "IMMOAPP_E2E_TEST_MODE"
Require-FlagZero -Name "IMMOAPP_E2E_TEST_MODE_DOCKER"

$publicBaseUrl = Require-Env -Name "IMMOAPP_PUBLIC_BASE_URL"
if (-not $publicBaseUrl.ToLower().StartsWith("https://")) {
    throw "IMMOAPP_PUBLIC_BASE_URL must start with https://"
}

$tlsDomain = Require-Env -Name "IMMOAPP_TLS_DOMAIN"
$allowedHosts = Require-Env -Name "DJANGO_ALLOWED_HOSTS"
$allowedSet = @($allowedHosts.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($allowedSet -notcontains $tlsDomain) {
    throw "DJANGO_ALLOWED_HOSTS must include IMMOAPP_TLS_DOMAIN ($tlsDomain)."
}

Require-FlagOne -Name "SECURE_SSL_REDIRECT_DOCKER"
Require-FlagOne -Name "SESSION_COOKIE_SECURE_DOCKER"
Require-FlagOne -Name "CSRF_COOKIE_SECURE_DOCKER"

$baoAddr = Require-Env -Name "BAO_ADDR_DOCKER"
if (-not $baoAddr.ToLower().StartsWith("https://")) {
    throw "BAO_ADDR_DOCKER must use https:// in production."
}
Require-FlagOne -Name "BAO_VERIFY_SSL_DOCKER"
$null = Require-Env -Name "BAO_CACERT_DOCKER"

$null = Require-Env -Name "POSTGRES_DB"
$null = Require-Env -Name "POSTGRES_ADMIN_USER"
$null = Require-Env -Name "POSTGRES_ADMIN_PASSWORD" -InvalidValue "immoapp_admin_password"
$null = Require-Env -Name "POSTGRES_USER"
$null = Require-Env -Name "POSTGRES_PASSWORD" -InvalidValue "immoapp_app_password"
$null = Require-Env -Name "RABBITMQ_USER"
$null = Require-Env -Name "RABBITMQ_PASSWORD" -InvalidValue "immoapp_rabbit_password"
$null = Require-Env -Name "MINIO_ROOT_USER"
$null = Require-Env -Name "MINIO_ROOT_PASSWORD"
$null = Require-Env -Name "MINIO_KMS_SECRET_KEY"
$null = Require-Env -Name "STORAGE_BUCKET"

$secretsHostDir = Get-EnvValueFromFile -Path $EnvFile -Name "IMMOAPP_SECRETS_HOST_DIR"
if ([string]::IsNullOrWhiteSpace($secretsHostDir)) {
    $secretsHostDir = "C:\ProgramData\ImmoApp\secrets"
}
if (-not (Test-Path $secretsHostDir)) {
    throw "Secrets directory not found: $secretsHostDir"
}

$tlsDir = Require-Env -Name "IMMOAPP_OPENBAO_TLS_DIR"
if (-not (Test-Path $tlsDir)) {
    throw "OpenBao TLS directory not found: $tlsDir"
}
foreach ($name in @("ca.crt", "server.crt", "server.key")) {
    $path = Join-Path $tlsDir $name
    if (-not (Test-Path $path)) {
        throw "Missing OpenBao TLS file: $path"
    }
}

$approleFile = Join-Path $secretsHostDir "openbao-approle.json"
if (-not (Test-Path $approleFile)) {
    throw "Missing OpenBao AppRole file: $approleFile"
}

Write-Host "[preflight-prod] OK" -ForegroundColor Green
