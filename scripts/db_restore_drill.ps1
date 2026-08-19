$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
Set-ImmoAppSecurityEnv

param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile
)

if (-not (Test-Path $BackupFile)) {
    throw "Backup file not found: $BackupFile"
}

$dbUser = $env:POSTGRES_ADMIN_USER
$dbPass = $env:POSTGRES_ADMIN_PASSWORD
$dbHost = if ($env:POSTGRES_HOST) { $env:POSTGRES_HOST } else { "127.0.0.1" }
$dbPort = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { "5432" }
$testDb = "immoapp_restore_drill"

if (-not $dbUser -or -not $dbPass) {
    throw "POSTGRES_ADMIN_USER / POSTGRES_ADMIN_PASSWORD are required."
}

$serverPython = Get-ImmoAppVenvPython -Kind server
if (-not (Test-Path $serverPython)) {
    throw "Server venv python not found at $serverPython"
}

$env:PGPASSWORD = $dbPass
try {
    & psql -h $dbHost -p $dbPort -U $dbUser -d postgres -c "DROP DATABASE IF EXISTS $testDb;"
    if ($LASTEXITCODE -ne 0) { throw "DROP DATABASE failed with exit code $LASTEXITCODE" }

    & psql -h $dbHost -p $dbPort -U $dbUser -d postgres -c "CREATE DATABASE $testDb;"
    if ($LASTEXITCODE -ne 0) { throw "CREATE DATABASE failed with exit code $LASTEXITCODE" }

    & pg_restore -h $dbHost -p $dbPort -U $dbUser -d $testDb --clean --if-exists $BackupFile
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }

    $env:POSTGRES_DB = $testDb

    & $serverPython scripts/verify_security_schema.py
    if ($LASTEXITCODE -ne 0) { throw "verify_security_schema.py failed with exit code $LASTEXITCODE" }

    & $serverPython server/manage.py test server.api.tests.test_firewall --noinput
    if ($LASTEXITCODE -ne 0) { throw "Django firewall test failed with exit code $LASTEXITCODE" }

    Write-Host "Restore drill passed on database '$testDb'." -ForegroundColor Green
}
finally {
    $env:PGPASSWORD = $null
}
