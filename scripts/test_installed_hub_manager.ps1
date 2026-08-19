param(
    [string]$InstalledHubManagerPath = "$env:LOCALAPPDATA\Programs\ImmoApp Beta\ImmoApp Hub Manager.exe",
    [Parameter(Mandatory = $true)][string]$SourceCommitSha,
    [string]$FrontDoorUrl = "http://127.0.0.1:18001",
    [string]$PlatformAdminEmail = "e2e-platform-admin@example.test",
    [switch]$IncludeElevated,
    [switch]$KeepManagedHubRunning,
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-ImmoAppHostWindows) -or -not [Environment]::UserInteractive) {
    throw "Installed Hub Manager E2E requires an interactive Windows desktop."
}
if (-not (Test-Path -LiteralPath $InstalledHubManagerPath -PathType Leaf)) {
    throw "Installed Hub Manager executable not found: $InstalledHubManagerPath"
}
if ($IncludeElevated -and -not (Test-ImmoAppCurrentProcessElevated)) {
    throw "-IncludeElevated requires launching this runner from an elevated PowerShell window."
}
Assert-ImmoAppLowerGitSha -Value $SourceCommitSha -Name "SourceCommitSha"

$serverPython = Assert-ImmoAppVenvPython -Kind server -Purpose "installed Hub Manager E2E"
$clientPython = Assert-ImmoAppVenvPython -Kind client -Purpose "installed Hub Manager E2E"
$installedRoot = Split-Path -Parent ([System.IO.Path]::GetFullPath($InstalledHubManagerPath))
$installedScript = Join-Path $installedRoot "scripts\hub_manager.ps1"
if (-not (Test-Path -LiteralPath $installedScript -PathType Leaf)) {
    throw "Installed Hub Manager PowerShell authority not found: $installedScript"
}

$bootstrapNames = @(
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
Set-ImmoAppEnvFromBootstrapSecrets -Names $bootstrapNames

$uri = [Uri]$FrontDoorUrl
if (-not $uri.IsLoopback -or $uri.Scheme -ne "http") {
    throw "Installed Hub Manager E2E front door must be loopback HTTP."
}
$frontDoorPort = if ($uri.IsDefaultPort) { 80 } else { $uri.Port }
$paths = Ensure-ImmoAppRuntimeLayout
$envFile = Join-Path $paths.ConfigRoot ".env.local"
$previousEnvBytes = if (Test-Path -LiteralPath $envFile -PathType Leaf) {
    [System.IO.File]::ReadAllBytes($envFile)
}
else {
    $null
}

$env:IMMOAPP_E2E_TEST_MODE = "1"
$env:IMMOAPP_E2E_INSTALLED_HUB_MANAGER_PATH = [System.IO.Path]::GetFullPath($InstalledHubManagerPath)
$env:IMMOAPP_E2E_INSTALLED_SOURCE_COMMIT_SHA = $SourceCommitSha
$env:IMMOAPP_E2E_MANAGED_FRONT_DOOR_URL = $FrontDoorUrl.TrimEnd("/")
$env:IMMOAPP_E2E_MANAGED_PLATFORM_ADMIN_EMAIL = $PlatformAdminEmail
$env:IMMOAPP_PLATFORM_ADMIN_EMAIL = $PlatformAdminEmail
$env:IMMOAPP_PUBLIC_BASE_URL = $FrontDoorUrl.TrimEnd("/")
$env:IMMOAPP_E2E_CLIENT_PYTHON = $clientPython

$startOutput = Join-Path $paths.LogsRoot "installed-hub-manager-e2e-start.json"
$preStopOutput = Join-Path $paths.LogsRoot "installed-hub-manager-e2e-pre-stop.json"
$stopOutput = Join-Path $paths.LogsRoot "installed-hub-manager-e2e-stop.json"
$tests = @(
    "app/tests/e2e_desktop/test_installed_hub_manager.py",
    "app/tests/e2e_desktop/test_installed_hub_manager_first_owner.py",
    "app/tests/e2e_desktop/test_installed_hub_manager_runtime.py",
    "app/tests/e2e_desktop/test_installed_hub_manager_setup.py",
    "app/tests/e2e_desktop/test_installed_hub_manager_utilities.py"
)
$marker = if ($IncludeElevated) {
    "installed_hub_manager and not hub_manager_docker_bootstrap"
}
else {
    "installed_hub_manager and not installed_hub_manager_elevated and not hub_manager_docker_bootstrap"
}

function Test-InstalledHubManagerFrontDoorReady {
    try {
        $response = Invoke-WebRequest `
            -Method Get `
            -Uri ($FrontDoorUrl.TrimEnd("/") + "/api/v1/health/") `
            -TimeoutSec 3 `
            -UseBasicParsing
        return ([int]$response.StatusCode -eq 200)
    }
    catch {
        return $false
    }
}

function Wait-InstalledHubManagerFrontDoorStopped {
    param([int]$TimeoutSeconds = 120)

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-InstalledHubManagerFrontDoorReady)) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Installed managed Hub front door remained reachable after stop: $FrontDoorUrl"
}

try {
    Set-ImmoAppEnvFileValue -Path $envFile -Name "IMMOAPP_HUB_FRONT_DOOR_PORT" -Value ([string]$frontDoorPort)
    Set-ImmoAppEnvFileValue -Path $envFile -Name "IMMOAPP_HUB_FRONT_DOOR_URL" -Value $FrontDoorUrl.TrimEnd("/")
    Set-ImmoAppEnvFileValue -Path $envFile -Name "IMMOAPP_PLATFORM_ADMIN_EMAIL" -Value $PlatformAdminEmail
    Set-ImmoAppEnvFileValue -Path $envFile -Name "IMMOAPP_PUBLIC_BASE_URL" -Value $FrontDoorUrl.TrimEnd("/")

    & powershell -NoProfile -ExecutionPolicy Bypass -File $installedScript `
        -Action stop `
        -HubBaseUrl $FrontDoorUrl `
        -OutputJson $preStopOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Installed managed Hub pre-test stop failed. Evidence: $preStopOutput"
    }
    Wait-InstalledHubManagerFrontDoorStopped

    & powershell -NoProfile -ExecutionPolicy Bypass -File $installedScript `
        -Action start `
        -HubBaseUrl $FrontDoorUrl `
        -OutputJson $startOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Installed managed Hub bootstrap failed. Evidence: $startOutput"
    }

    $command = @(
        "-m",
        "pytest"
    ) + $tests + @(
        "-m",
        $marker,
        "--e2e-client-python",
        $clientPython,
        "-v",
        "--tb=short"
    )
    if ($PytestArgs.Count -gt 0) {
        $command += $PytestArgs
    }
    & $serverPython @command
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Hub Manager E2E failed with exit code $LASTEXITCODE"
    }
}
finally {
    if (-not $KeepManagedHubRunning) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $installedScript `
            -Action stop `
            -HubBaseUrl $FrontDoorUrl `
            -OutputJson $stopOutput | Out-Null
        Wait-InstalledHubManagerFrontDoorStopped
    }
    if ($null -eq $previousEnvBytes) {
        Remove-Item -LiteralPath $envFile -Force -ErrorAction SilentlyContinue
    }
    else {
        [System.IO.File]::WriteAllBytes($envFile, $previousEnvBytes)
    }
}
