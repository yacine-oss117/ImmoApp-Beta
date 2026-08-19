param(
    [ValidateSet("smoke", "nightly")]
    [string]$Suite = "smoke",
    [string]$BaseUrl = "",
    [string]$FrontDoorUrl = "",
    [string]$ClientPython = "",
    [string]$ServerLogPath = "",
    [int]$ArtifactRetentionDays = 7,
    [double]$ApiTimeoutSeconds = 12.0,
    [switch]$KeepPassingArtifacts,
    [switch]$EnsureBackend,
    [switch]$RebuildBackend,
    [switch]$UseHubFrontDoor,
    [switch]$AllowSyncedContainer,
    [switch]$SyncContainers,
    [switch]$PreflightRunner = $true,
    [switch]$ResetRunner,
    [switch]$SkipRunnerPreflight,
    [switch]$CleanArtifacts,
    [switch]$CleanPytestCache,
    [switch]$KillStaleDesktopProcesses,
    [switch]$KillStaleServerProcesses,
    [int]$WarnFreeMemoryGb = 6,
    [int]$MinCriticalFreeMemoryGb = 1,
    [int]$MinCommitHeadroomGb = 2,
    [int]$MinFreeMemoryGb = -1,
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-ImmoAppHostWindows)) {
    throw "Native desktop E2E requires a Windows host."
}
if (-not [Environment]::UserInteractive) {
    throw "Native desktop E2E requires an interactive desktop session."
}
if ($SyncContainers -or $AllowSyncedContainer) {
    throw (
        "Product desktop E2E no longer supports -SyncContainers or -AllowSyncedContainer. " +
        "Use -RebuildBackend, or run against a backend whose image build identity already matches this checkout."
    )
}

$paths = Ensure-ImmoAppTools
Set-ImmoAppCacheEnv -Paths $paths
Set-ImmoAppSecurityEnv
Import-ImmoAppEnvFile
Set-ImmoAppHostRuntimeEndpoints
$env:IMMOAPP_E2E_TEST_MODE = "1"
$env:IMMOAPP_E2E_TEST_MODE_DOCKER = "1"

$repoRoot = Get-ImmoAppRepoRoot
$serverPython = Assert-ImmoAppVenvPython -Kind server -Purpose "desktop E2E"
$resolvedClientPython = if ([string]::IsNullOrWhiteSpace($ClientPython)) {
    Assert-ImmoAppVenvPython -Kind client -Purpose "desktop E2E"
}
else {
    (Resolve-Path $ClientPython).Path
}

if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) {
    $env:IMMOAPP_E2E_BASE_URL = $BaseUrl.Trim()
}
elseif (-not $env:IMMOAPP_E2E_BASE_URL) {
    $env:IMMOAPP_E2E_BASE_URL = if ($UseHubFrontDoor) { "http://127.0.0.1:18000" } else { "http://127.0.0.1:8000" }
}

if ($UseHubFrontDoor) {
    $env:COMPOSE_PROFILES = "hub-front-door"
    $env:IMMOAPP_BACKEND_HOST_PORT = "18000"
    $env:IMMOAPP_WEB_BIND_HOST = "127.0.0.1"
    $env:IMMOAPP_CADDY_BIND_HOST = "127.0.0.1"
    if (-not $env:IMMOAPP_HUB_FRONT_DOOR_PORT) {
        $env:IMMOAPP_HUB_FRONT_DOOR_PORT = "8000"
    }
}

if (-not [string]::IsNullOrWhiteSpace($FrontDoorUrl)) {
    $env:IMMOAPP_E2E_FRONT_DOOR_URL = $FrontDoorUrl.Trim()
}
elseif ($UseHubFrontDoor -and -not $env:IMMOAPP_E2E_FRONT_DOOR_URL) {
    $env:IMMOAPP_E2E_FRONT_DOOR_URL = "http://127.0.0.1:$($env:IMMOAPP_HUB_FRONT_DOOR_PORT)"
}

$artifactRoot = Join-Path $repoRoot ".tmp\desktop_e2e_artifacts"
$runtimePaths = Ensure-ImmoAppRuntimeLayout
$e2eBootstrapNames = @(
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

function Initialize-E2ERuntimeEnvFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourceEnvFile,
        [string]$PublicBaseUrl,
        [string]$PlatformAdminEmail
    )

    if (-not (Test-Path -LiteralPath $SourceEnvFile)) {
        throw "Canonical runtime env file not found for desktop E2E: $SourceEnvFile"
    }

    $runtimeEnvRoot = Join-Path $runtimePaths.TmpRoot "desktop-e2e-runtime"
    if (-not (Test-Path -LiteralPath $runtimeEnvRoot)) {
        New-Item -ItemType Directory -Path $runtimeEnvRoot -Force | Out-Null
    }
    $e2eEnvFile = Join-Path $runtimeEnvRoot ".env.e2e.local"
    Copy-Item -LiteralPath $SourceEnvFile -Destination $e2eEnvFile -Force

    foreach ($name in $e2eBootstrapNames) {
        $value = [Environment]::GetEnvironmentVariable($name, "Process")
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            Set-ImmoAppEnvFileValue -Path $e2eEnvFile -Name $name -Value $value
        }
    }

    Set-ImmoAppEnvFileValue -Path $e2eEnvFile -Name "IMMOAPP_PLATFORM_ADMIN_EMAIL" -Value $PlatformAdminEmail
    Set-ImmoAppEnvFileValue -Path $e2eEnvFile -Name "IMMOAPP_PUBLIC_BASE_URL" -Value $PublicBaseUrl
    return $e2eEnvFile
}

$ownerLifecyclePlatformAdminEmail = if (-not [string]::IsNullOrWhiteSpace($env:IMMOAPP_PLATFORM_ADMIN_EMAIL)) {
    $env:IMMOAPP_PLATFORM_ADMIN_EMAIL.Trim()
}
else {
    "e2e-platform-admin@example.test"
}
$ownerLifecyclePublicBaseUrl = if (-not [string]::IsNullOrWhiteSpace($env:IMMOAPP_PUBLIC_BASE_URL)) {
    $env:IMMOAPP_PUBLIC_BASE_URL.Trim().TrimEnd("/")
}
elseif (-not [string]::IsNullOrWhiteSpace($env:IMMOAPP_E2E_FRONT_DOOR_URL)) {
    $env:IMMOAPP_E2E_FRONT_DOOR_URL.Trim().TrimEnd("/")
}
else {
    $env:IMMOAPP_E2E_BASE_URL.Trim().TrimEnd("/")
}
$env:IMMOAPP_PLATFORM_ADMIN_EMAIL = $ownerLifecyclePlatformAdminEmail
$env:IMMOAPP_PUBLIC_BASE_URL = $ownerLifecyclePublicBaseUrl
Set-ImmoAppEnvFromBootstrapSecrets -Names $e2eBootstrapNames
if ($RebuildBackend -or $EnsureBackend) {
    $env:IMMOAPP_RUNTIME_ENV_FILE = Initialize-E2ERuntimeEnvFile `
        -SourceEnvFile (Get-ImmoAppDefaultEnvFile) `
        -PublicBaseUrl $ownerLifecyclePublicBaseUrl `
        -PlatformAdminEmail $ownerLifecyclePlatformAdminEmail
}

$effectiveMinCriticalFreeMemoryGb = if ($MinFreeMemoryGb -ge 0) {
    $MinFreeMemoryGb
}
else {
    $MinCriticalFreeMemoryGb
}
$marker = if ($Suite -eq "nightly") {
    "e2e and (e2e_smoke or e2e_nightly)"
}
else {
    "e2e and e2e_smoke"
}

function Format-E2EApiTimeoutSeconds {
    param([Parameter(Mandatory = $true)][double]$Value)

    if ([double]::IsNaN($Value) -or [double]::IsInfinity($Value) -or $Value -lt 3 -or $Value -gt 60) {
        throw "-ApiTimeoutSeconds must be a finite number between 3 and 60 seconds."
    }
    return [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:G}", $Value)
}

$apiTimeoutSecondsText = Format-E2EApiTimeoutSeconds -Value $ApiTimeoutSeconds
$backendPreflightTimeoutSeconds = [Math]::Max(30.0, [double]$apiTimeoutSecondsText)
$backendPreflightTimeoutSecondsText = [string]::Format(
    [Globalization.CultureInfo]::InvariantCulture,
    "{0:G}",
    $backendPreflightTimeoutSeconds
)
$env:IMMOAPP_E2E_API_TIMEOUT_SECONDS = $apiTimeoutSecondsText

function Invoke-E2ERunnerEnvironmentPreflight {
    param([Parameter(Mandatory = $true)][ValidateSet("check", "reset")][string]$Mode)

    $resetScript = Join-Path $PSScriptRoot "reset_e2e_environment.ps1"
    if (-not (Test-Path $resetScript)) {
        throw "Desktop E2E runner reset/preflight script not found: $resetScript"
    }

    $params = @{
        Mode = $Mode
        ArtifactRetentionDays = $ArtifactRetentionDays
        RequireInteractiveDesktop = $true
        RequireDocker = ($RebuildBackend -or $EnsureBackend)
        BaseUrl = $env:IMMOAPP_E2E_BASE_URL
        WarnFreeMemoryGb = $WarnFreeMemoryGb
        MinCriticalFreeMemoryGb = $effectiveMinCriticalFreeMemoryGb
        MinCommitHeadroomGb = $MinCommitHeadroomGb
    }
    if ($Mode -eq "reset") {
        if ($CleanArtifacts) {
            $params.CleanArtifacts = $true
        }
        if ($CleanPytestCache) {
            $params.CleanPytestCache = $true
        }
    }
    if ($KillStaleDesktopProcesses) {
        $params.KillStaleDesktopProcesses = $true
    }
    if ($KillStaleServerProcesses) {
        $params.KillStaleServerProcesses = $true
    }

    Write-Host "Runner environment $Mode preflight:"
    try {
        & $resetScript @params
    }
    catch {
        throw "Desktop E2E runner environment $Mode preflight failed: $($_.Exception.Message)"
    }
}

function Invoke-E2EStack {
    param([Parameter(Mandatory = $true)][string]$Action)
    $stackArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $PSScriptRoot "stack.ps1"),
        "-Action",
        $Action
    )
    if (-not [string]::IsNullOrWhiteSpace($env:IMMOAPP_RUNTIME_ENV_FILE)) {
        $stackArgs += @("-EnvFile", $env:IMMOAPP_RUNTIME_ENV_FILE)
    }
    & powershell @stackArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Backend stack action failed: $Action"
    }
}

if ($SkipRunnerPreflight -and $ResetRunner) {
    throw "-ResetRunner cannot be combined with -SkipRunnerPreflight."
}

if (-not $SkipRunnerPreflight) {
    if ($ResetRunner) {
        Invoke-E2ERunnerEnvironmentPreflight -Mode "reset"
    }
    if ($PreflightRunner -or $ResetRunner) {
        Invoke-E2ERunnerEnvironmentPreflight -Mode "check"
    }
}

if ($RebuildBackend) {
    Invoke-E2EStack -Action "up"
}
elseif ($EnsureBackend) {
    Invoke-E2EStack -Action "up-existing"
}

$preflightCommand = @(
    "-m",
    "app.tests.e2e_desktop.preflight_cli",
    "--base-url",
    $env:IMMOAPP_E2E_BASE_URL,
    "--timeout",
    $backendPreflightTimeoutSecondsText
)
Write-Host "Backend identity preflight:"
& $serverPython @preflightCommand
if ($LASTEXITCODE -ne 0) {
    throw "Desktop E2E backend identity preflight failed with exit code $LASTEXITCODE"
}

$pytestCommand = @(
    "-m",
    "pytest",
    "app/tests/e2e_desktop",
    "-m",
    $marker,
    "--e2e-base-url",
    $env:IMMOAPP_E2E_BASE_URL,
    "--e2e-client-python",
    $resolvedClientPython,
    "--e2e-artifact-retention-days",
    "$ArtifactRetentionDays",
    "--e2e-api-timeout-seconds",
    $apiTimeoutSecondsText,
    "-v",
    "--tb=short"
)

if (-not [string]::IsNullOrWhiteSpace($env:IMMOAPP_E2E_FRONT_DOOR_URL)) {
    $pytestCommand += @("--e2e-front-door-url", $env:IMMOAPP_E2E_FRONT_DOOR_URL)
}

if ($KeepPassingArtifacts) {
    $pytestCommand += @("--e2e-keep-passing-artifacts")
}

if (-not [string]::IsNullOrWhiteSpace($ServerLogPath)) {
    $pytestCommand += @("--e2e-server-log-path", (Resolve-Path $ServerLogPath).Path)
}

if ($PytestArgs.Count -gt 0) {
    $pytestCommand += $PytestArgs
}

Write-Host "Running native desktop E2E"
Write-Host "Suite:     $Suite"
Write-Host "Base URL:  $env:IMMOAPP_E2E_BASE_URL"
Write-Host "Front door URL: $env:IMMOAPP_E2E_FRONT_DOOR_URL"
Write-Host "Server Py: $serverPython"
Write-Host "Client Py: $resolvedClientPython"
Write-Host "Artifacts: $artifactRoot"
Write-Host "Runtime env file: $env:IMMOAPP_RUNTIME_ENV_FILE"
Write-Host "Owner onboarding public URL: $ownerLifecyclePublicBaseUrl"
Write-Host "Owner onboarding platform admin: $ownerLifecyclePlatformAdminEmail"
Write-Host "Retention: $ArtifactRetentionDays day(s)"
Write-Host "API timeout: $apiTimeoutSecondsText second(s)"
Write-Host "Marker:    $marker"
Write-Host "Ensure backend:         $EnsureBackend"
Write-Host "Rebuild backend:        $RebuildBackend"
Write-Host "Use Hub front door:     $UseHubFrontDoor"
Write-Host "Verify backend identity: mandatory"
Write-Host "Runner preflight:       $PreflightRunner"
Write-Host "Reset runner:           $ResetRunner"
Write-Host "Skip runner preflight:  $SkipRunnerPreflight"
Write-Host "Clean artifacts:        $CleanArtifacts"
Write-Host "Clean pytest cache:     $CleanPytestCache"
Write-Host "Warn free memory GB:    $WarnFreeMemoryGb"
Write-Host "Critical free memory GB: $effectiveMinCriticalFreeMemoryGb"
Write-Host "Min commit headroom GB: $MinCommitHeadroomGb"
Write-Host ""
Write-Host "Backend identity must match this checkout before any desktop process is launched."

Push-Location $repoRoot
try {
    & $serverPython @pytestCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop E2E suite failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
