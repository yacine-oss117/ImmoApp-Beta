param(
    [string]$BaseUrl = "",
    [string]$FrontDoorUrl = "",
    [int]$ArtifactRetentionDays = 7,
    [double]$ApiTimeoutSeconds = 12.0,
    [int]$WarnFreeMemoryGb = 6,
    [int]$MinCriticalFreeMemoryGb = 1,
    [int]$MinCommitHeadroomGb = 2,
    [switch]$CleanPytestCache,
    [switch]$KeepPassingArtifacts,
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$repoRoot = Get-ImmoAppRepoRoot
$serverPython = Assert-ImmoAppVenvPython -Kind server -Purpose "release E2E dependency audit"
$artifactRoot = Join-Path $repoRoot ".tmp\desktop_e2e_artifacts"
$resetScript = Join-Path $PSScriptRoot "reset_e2e_environment.ps1"
$e2eScript = Join-Path $PSScriptRoot "test_e2e_desktop.ps1"
$depAuditScript = Join-Path $repoRoot "scripts\verify_dependency_vulns.py"

function Format-E2EApiTimeoutSeconds {
    param([Parameter(Mandatory = $true)][double]$Value)

    if ([double]::IsNaN($Value) -or [double]::IsInfinity($Value) -or $Value -lt 3 -or $Value -gt 60) {
        throw "-ApiTimeoutSeconds must be a finite number between 3 and 60 seconds."
    }
    return [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:G}", $Value)
}

$apiTimeoutSecondsText = Format-E2EApiTimeoutSeconds -Value $ApiTimeoutSeconds

$resetParams = @{
    Mode = "reset"
    ArtifactRetentionDays = $ArtifactRetentionDays
    CleanArtifacts = $true
    KillStaleDesktopProcesses = $true
    KillStaleServerProcesses = $true
    RequireInteractiveDesktop = $true
    WarnFreeMemoryGb = $WarnFreeMemoryGb
    MinCriticalFreeMemoryGb = $MinCriticalFreeMemoryGb
    MinCommitHeadroomGb = $MinCommitHeadroomGb
}
if ($CleanPytestCache) {
    $resetParams.CleanPytestCache = $true
}
if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) {
    $resetParams.BaseUrl = $BaseUrl.Trim()
}

function Reset-BackendStackResources {
    param(
        [Parameter(Mandatory = $true)][string]$Reason
    )

    Write-Host "Release E2E validation: resetting backend stack $Reason"
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "stack.ps1") -Action "down"
        if ($LASTEXITCODE -ne 0) {
            throw "Backend stack down failed with exit code $LASTEXITCODE"
        }
        & wsl --shutdown
        if ($LASTEXITCODE -ne 0) {
            throw "wsl --shutdown failed with exit code $LASTEXITCODE"
        }
        & docker version | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Docker did not restart cleanly after WSL shutdown."
        }
    }
    catch {
        throw "Release E2E backend resource reset $Reason failed: $($_.Exception.Message)"
    }
}

Reset-BackendStackResources -Reason "before runner preflight"

Write-Host "Release E2E validation: resetting runner environment"
try {
    & $resetScript @resetParams
}
catch {
    throw "Release E2E runner reset failed: $($_.Exception.Message)"
}

function Invoke-DesktopE2E {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("smoke", "nightly")][string]$Suite,
        [switch]$RebuildBackend,
        [switch]$EnsureBackend
    )

    $params = @{
        Suite = $Suite
        ArtifactRetentionDays = $ArtifactRetentionDays
        WarnFreeMemoryGb = $WarnFreeMemoryGb
        MinCriticalFreeMemoryGb = $MinCriticalFreeMemoryGb
        MinCommitHeadroomGb = $MinCommitHeadroomGb
        ApiTimeoutSeconds = [double]$apiTimeoutSecondsText
        UseHubFrontDoor = $true
    }
    if ($RebuildBackend) {
        $params.RebuildBackend = $true
    }
    if ($EnsureBackend) {
        $params.EnsureBackend = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) {
        $params.BaseUrl = $BaseUrl.Trim()
    }
    if (-not [string]::IsNullOrWhiteSpace($FrontDoorUrl)) {
        $params.FrontDoorUrl = $FrontDoorUrl.Trim()
    }
    if ($KeepPassingArtifacts) {
        $params.KeepPassingArtifacts = $true
    }
    if ($PytestArgs.Count -gt 0) {
        $params.PytestArgs = $PytestArgs
    }

    Write-Host "Release E2E validation: running $Suite suite"
    try {
        & $e2eScript @params
    }
    catch {
        throw "Release E2E $Suite suite failed: $($_.Exception.Message)"
    }
}

Invoke-DesktopE2E -Suite "nightly" -RebuildBackend

Write-Host "Release E2E validation: auditing host and Docker backend dependency inventories"
$previousDepAuditEnforce = $env:IMMOAPP_ENFORCE_DEP_AUDIT
$previousDockerAuditRequired = $env:IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND
try {
    $env:IMMOAPP_ENFORCE_DEP_AUDIT = "1"
    $env:IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND = "1"
    & $serverPython $depAuditScript
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency vulnerability audit failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($null -eq $previousDepAuditEnforce) {
        Remove-Item Env:IMMOAPP_ENFORCE_DEP_AUDIT -ErrorAction SilentlyContinue
    }
    else {
        $env:IMMOAPP_ENFORCE_DEP_AUDIT = $previousDepAuditEnforce
    }
    if ($null -eq $previousDockerAuditRequired) {
        Remove-Item Env:IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND -ErrorAction SilentlyContinue
    }
    else {
        $env:IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND = $previousDockerAuditRequired
    }
}

Write-Host "Release E2E validation completed."
Write-Host "Artifacts: $artifactRoot"
