param(
    [string]$AdminUsername = "admin",
    [string[]]$PreserveUsername = @("fatima@example.com"),
    [switch]$UseWindowsVolumes,
    [switch]$NoWindowsVolumes,
    [switch]$SkipEndpointUpdate
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$runtimePaths = Ensure-ImmoAppRuntimeLayout
$bootstrapScript = Join-Path $PSScriptRoot "bootstrap_local_runtime.ps1"
$repoRoot = Get-ImmoAppRepoRoot
$envFile = Get-ImmoAppDefaultEnvFile
$serverPython = Assert-ImmoAppVenvPython -Kind server -Purpose "running scripts/dev_reset.ps1"
$stackScript = Join-Path $PSScriptRoot "stack.ps1"
$endpointScript = Join-Path $PSScriptRoot "set_client_api_endpoint.ps1"
$sanitizeScript = Join-Path $repoRoot "scripts\sanitize_local_dev_state.py"

if (-not (Test-Path $envFile)) {
    throw "Canonical env file not found: $envFile. Run '$bootstrapScript' first."
}

$envIssues = @(Get-ImmoAppEnvPlaceholderIssues -EnvFilePath $envFile)
if ($envIssues.Count -gt 0) {
    $lines = @()
    foreach ($issue in $envIssues) {
        $lines += " - $($issue.Key): $($issue.Message)"
    }
    throw "scripts/dev_reset.ps1 is a destructive reset for an already bootstrapped machine. Update $envFile first:`n$($lines -join "`n")"
}

if (-not (Test-Path $runtimePaths.BootstrapSecretsFile)) {
    throw "Local bootstrap secrets file not found: $($runtimePaths.BootstrapSecretsFile). Run '$bootstrapScript' first."
}

if (-not $SkipEndpointUpdate) {
    $null = Assert-ImmoAppVenvPython -Kind client -Purpose "running scripts/dev_reset.ps1"
}

function Invoke-StackAction {
    param([Parameter(Mandatory = $true)][string]$ActionName)

    $args = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $stackScript,
        "-Action",
        $ActionName
    )
    if ($UseWindowsVolumes) {
        $args += "-UseWindowsVolumes"
    }
    if ($NoWindowsVolumes) {
        $args += "-NoWindowsVolumes"
    }

    & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "stack.ps1 -Action $ActionName failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Preparing destructive Docker-local dev reset on an already bootstrapped machine..." -ForegroundColor Cyan
Invoke-StackAction -ActionName "up-infra"
Invoke-StackAction -ActionName "sync-secrets"
Invoke-StackAction -ActionName "db-prepare"

Write-Host "Sanitizing local data while preserving selected users..." -ForegroundColor Cyan
$env:IMMOAPP_ALLOW_DESTRUCTIVE_LOCAL_SANITIZE = "1"
$sanitizeArgs = @(
    $sanitizeScript,
    "--force-local",
    "--admin-username",
    $AdminUsername
)
foreach ($username in $PreserveUsername) {
    if ([string]::IsNullOrWhiteSpace($username)) {
        continue
    }
    $sanitizeArgs += @("--preserve-username", $username)
}
& $serverPython @sanitizeArgs
if ($LASTEXITCODE -ne 0) {
    throw "sanitize_local_dev_state.py failed with exit code $LASTEXITCODE"
}

Write-Host "Restarting app services on the cleaned stack..." -ForegroundColor Cyan
Invoke-StackAction -ActionName "restart-app"

if (-not $SkipEndpointUpdate) {
    Write-Host "Pointing the desktop client at Docker-local HTTPS..." -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File $endpointScript -BaseUrl "https://localhost"
    if ($LASTEXITCODE -ne 0) {
        throw "set_client_api_endpoint.ps1 failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Docker-local dev reset completed." -ForegroundColor Green
