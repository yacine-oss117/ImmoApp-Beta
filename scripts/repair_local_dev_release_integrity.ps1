param(
    [switch]$ConfirmDisposableLocalData,
    [switch]$Apply,
    [switch]$AllowNonDefaultLocalDatabase,
    [string]$JsonOut = ""
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
Set-ImmoAppSecurityEnv
Import-ImmoAppEnvFile
Set-ImmoAppHostRuntimeEndpoints

$repoRoot = Get-ImmoAppRepoRoot
$serverPython = Get-ImmoAppVenvPython -Kind server
if (-not (Test-Path $serverPython)) {
    throw "Server venv python not found at $serverPython"
}

$args = @(
    (Join-Path $repoRoot "scripts\repair_local_dev_release_integrity.py")
)
if ($Apply.IsPresent) {
    $args += "--apply"
}
if ($ConfirmDisposableLocalData.IsPresent) {
    $args += "--confirm-disposable-local-data"
}
if ($AllowNonDefaultLocalDatabase.IsPresent) {
    $args += "--allow-non-default-local-database"
}
if (-not [string]::IsNullOrWhiteSpace($JsonOut)) {
    $args += @("--json-out", $JsonOut)
}

Write-Host "Release integrity local-dev repair mode:" -ForegroundColor Yellow
if ($Apply.IsPresent) {
    Write-Host " - apply: requested" -ForegroundColor Yellow
}
else {
    Write-Host " - apply: not requested; dry-run/report-only" -ForegroundColor Yellow
}
Write-Host " - confirmation: $($ConfirmDisposableLocalData.IsPresent)" -ForegroundColor Yellow
Write-Host " - non-default DB override: $($AllowNonDefaultLocalDatabase.IsPresent)" -ForegroundColor Yellow

& $serverPython @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
