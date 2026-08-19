param(
    [switch]$ErrorOnly
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$paths = Ensure-ImmoAppTools
Set-ImmoAppCacheEnv -Paths $paths
$repoRoot = Get-ImmoAppRepoRoot
Set-ImmoAppSecurityEnv
Set-ImmoAppHostRuntimeEndpoints
$APPDATA_ROOT = $paths.AppDataRoot
if (-not $env:DJANGO_ENV_FILE) {
    $env:DJANGO_ENV_FILE = Get-ImmoAppDefaultEnvFile
}
$envFile = $env:DJANGO_ENV_FILE

if ($ErrorOnly) {
    $env:DJANGO_LOG_LEVEL = "ERROR"
    $env:IMMOAPP_LOG_LEVEL = "ERROR"
}

# Log
Write-Host "Starting ImmoApp Django server..."
Write-Host "AppData: $APPDATA_ROOT"
Write-Host "Caches:  $env:PYTHONPYCACHEPREFIX"
Write-Host "Repo:    $repoRoot"
Write-Host "Env:     $envFile"
Write-Host "Mode:    Host-local debug runtime (Docker-local stack remains primary)"
if ($ErrorOnly) {
    Write-Host "Logs:    ERROR only"
}
if (-not (Test-Path $envFile)) {
    Write-Warning "Env file not found at $envFile. Server will rely on process environment only."
}

$VENV_PYTHON = Get-ImmoAppVenvPython -Kind server

# Run Server
$env:PYTHONPATH = $repoRoot
& $VENV_PYTHON -X pycache_prefix="$($paths.Pycache)" -u server\manage.py runserver 0.0.0.0:8000
