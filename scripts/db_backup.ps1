$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
Set-ImmoAppSecurityEnv

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = Join-Path $env:PROGRAMDATA "ImmoApp\backups"
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

$dbName = $env:POSTGRES_DB
$dbUser = $env:POSTGRES_ADMIN_USER
$dbPass = $env:POSTGRES_ADMIN_PASSWORD
$dbHost = if ($env:POSTGRES_HOST) { $env:POSTGRES_HOST } else { "127.0.0.1" }
$dbPort = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { "5432" }

if (-not $dbName -or -not $dbUser -or -not $dbPass) {
    throw "POSTGRES_DB / POSTGRES_ADMIN_USER / POSTGRES_ADMIN_PASSWORD are required."
}

$targetFile = Join-Path $backupRoot ("immoapp_" + $timestamp + ".dump")
$env:PGPASSWORD = $dbPass
try {
    & pg_dump -h $dbHost -p $dbPort -U $dbUser -d $dbName -Fc -f $targetFile
    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump failed with exit code $LASTEXITCODE"
    }
    Write-Host "Backup created: $targetFile" -ForegroundColor Green
}
finally {
    $env:PGPASSWORD = $null
}
