param(
    [string]$BaseUrl = "",
    [switch]$ErrorOnly
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

# Older elevated bootstraps could leave ProgramData host-local files writable
# only by Administrators. Repair once through UAC, then continue as the normal
# desktop user.
Invoke-ImmoAppRuntimePermissionRepairIfNeeded -AutoRepair | Out-Null

$paths = Ensure-ImmoAppTools
Set-ImmoAppCacheEnv -Paths $paths
$repoRoot = Get-ImmoAppRepoRoot
Set-ImmoAppHostRuntimeEndpoints
$APPDATA_ROOT = $paths.AppDataRoot
$env:IMMOAPP_APPDATA_ROOT = $APPDATA_ROOT
if (-not $env:DJANGO_ENV_FILE) {
    $env:DJANGO_ENV_FILE = Get-ImmoAppDefaultEnvFile
}
$envFile = $env:DJANGO_ENV_FILE

if ($ErrorOnly) {
    $env:IMMOAPP_LOG_LEVEL = "ERROR"
}

Write-Host "Starting ImmoApp client..."
Write-Host "AppData: $APPDATA_ROOT"
Write-Host "Caches:  $env:PYTHONPYCACHEPREFIX"
Write-Host "Repo:    $repoRoot"
Write-Host "Env:     $envFile"
Write-Host "Mode:    Docker-local primary (host-local only when explicitly overridden)"
if ($ErrorOnly) {
    Write-Host "Logs:    ERROR only"
}
if (-not (Test-Path $envFile)) {
    Write-Warning "Env file not found at $envFile. Client may fail if required config is missing."
}

$VENV_PYTHON = Get-ImmoAppVenvPython -Kind client
if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) {
    $env:IMMOAPP_API_BASE_URL = $BaseUrl.Trim()
}
elseif (-not $env:IMMOAPP_API_BASE_URL) {
    $env:IMMOAPP_API_BASE_URL = "https://localhost"
}
Write-Host "API:     $env:IMMOAPP_API_BASE_URL"

& $VENV_PYTHON -X pycache_prefix="$($paths.Pycache)" -u app\main.py
