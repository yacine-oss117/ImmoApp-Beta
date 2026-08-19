param(
    [Parameter(Mandatory = $true)][string]$InstalledExePath,
    [Parameter(Mandatory = $true)][string]$FrontDoorUrl,
    [Parameter(Mandatory = $true)][string]$InstallerSha256,
    [Parameter(Mandatory = $true)][string]$SourceCommitSha,
    [Parameter(Mandatory = $true)][string]$OutputJson,
    [string]$ExpectedConfigPath = "",
    [string]$InstalledInventoryJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Join-UrlPath {
    param([Parameter(Mandatory = $true)][string]$BaseUrl, [Parameter(Mandatory = $true)][string]$Path)
    return $BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

function Normalize-UrlForCompare {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return "" }
    return $Url.Trim().TrimEnd("/")
}

function Test-InternalBackendPort {
    param([string]$Url)
    try { $uri = [Uri]$Url } catch { return $true }
    return ([int]$uri.Port -in @(18000, 5432, 5672, 6379, 8200, 9000, 9001))
}

function Read-ClientConfig {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return [ordered]@{ status = "missing"; path = ""; base_url = ""; connection_source = ""; reason = "expected_config_path_not_supplied" }
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ status = "missing"; path = $Path; base_url = ""; connection_source = ""; reason = "expected_config_path_missing" }
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
        return [ordered]@{ status = "NO-GO"; path = $Path; base_url = ""; connection_source = ""; reason = "expected_config_path_reparse_point" }
    }
    $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    return [ordered]@{
        status = "present"
        path = (Resolve-Path -LiteralPath $Path).Path
        base_url = [string]$payload.base_url
        connection_source = [string]$payload.connection_source
        reason = ""
    }
}

if (-not (Test-Path -LiteralPath $InstalledExePath -PathType Leaf)) {
    throw "Installed desktop executable not found: $InstalledExePath"
}
if (Test-ImmoAppPathHasReparsePoint -Path $InstalledExePath) {
    throw "Installed desktop executable path contains a reparse point, symlink, or junction: $InstalledExePath"
}
if ($InstallerSha256 -notmatch "^[0-9a-f]{64}$") {
    throw "InstallerSha256 must be a lowercase SHA-256 hex string."
}
if ($SourceCommitSha -notmatch "^[0-9a-f]{40}$") {
    throw "SourceCommitSha must be a lowercase 40-character Git SHA."
}
if (Test-InternalBackendPort -Url $FrontDoorUrl) {
    throw "Installed desktop front-door proof refuses backend/internal service ports: $FrontDoorUrl"
}

$frontDoor = Normalize-UrlForCompare -Url $FrontDoorUrl
$installedExeSha = Get-ImmoAppFileSha256 -Path $InstalledExePath
$inventorySha = ""
$inventoryExeSha = ""
if ($InstalledInventoryJson) {
    if (-not (Test-Path -LiteralPath $InstalledInventoryJson -PathType Leaf)) {
        throw "Installed inventory JSON not found: $InstalledInventoryJson"
    }
    $inventory = Get-Content -LiteralPath $InstalledInventoryJson -Raw | ConvertFrom-Json
    if ([string]$inventory.kind -ne "immoapp_installed_app_inventory") {
        throw "Installed inventory evidence has wrong kind."
    }
    $inventorySha = Get-ImmoAppFileSha256 -Path $InstalledInventoryJson
    $inventoryExeSha = [string]$inventory.installed_exe_sha256
    if ($inventoryExeSha -and $inventoryExeSha.ToLowerInvariant() -ne $installedExeSha) {
        throw "Installed executable SHA does not match installed inventory."
    }
}

$healthStatus = 0
$identityStatus = 0
$frontDoorHeader = ""
$identityKind = ""
$identitySchema = 0
$failureReason = ""
try {
    $health = Invoke-WebRequest -Method Get -Uri (Join-UrlPath -BaseUrl $frontDoor -Path "/api/v1/health/") -TimeoutSec 8 -UseBasicParsing
    $healthStatus = [int]$health.StatusCode
    $identity = Invoke-WebRequest -Method Get -Uri (Join-UrlPath -BaseUrl $frontDoor -Path "/api/v1/hub/front-door/identity/") -TimeoutSec 8 -UseBasicParsing
    $identityStatus = [int]$identity.StatusCode
    $frontDoorHeader = [string]$identity.Headers["X-ImmoApp-Front-Door"]
    $identityPayload = $identity.Content | ConvertFrom-Json
    $identityKind = [string]$identityPayload.kind
    $identitySchema = [int]$identityPayload.schema_version
}
catch {
    $failureReason = "front_door_probe_failed: $($_.Exception.Message)"
}

$config = Read-ClientConfig -Path $ExpectedConfigPath
$persistedBaseUrl = Normalize-UrlForCompare -Url ([string]$config.base_url)
$connectionSource = [string]$config.connection_source
$checks = New-Object System.Collections.Generic.List[string]
if ($healthStatus -ne 200) { $checks.Add("health_status_not_200") }
if ($identityStatus -ne 200) { $checks.Add("identity_status_not_200") }
if ($frontDoorHeader.ToLowerInvariant() -ne "caddy") { $checks.Add("missing_caddy_front_door_header") }
if ($identityKind -ne "immoapp_hub_front_door_identity") { $checks.Add("invalid_front_door_identity_kind") }
if ($identitySchema -ne 1) { $checks.Add("invalid_front_door_identity_schema") }
if ([string]$config.status -ne "present") { $checks.Add("persisted_config_missing") }
if ($persistedBaseUrl -ne $frontDoor) { $checks.Add("persisted_config_not_front_door_url") }
if ($connectionSource -eq "local_dev_unverified") { $checks.Add("local_dev_unverified_not_allowed") }
if (Test-InternalBackendPort -Url $persistedBaseUrl) { $checks.Add("persisted_config_uses_backend_internal_port") }
if ($failureReason) { $checks.Add("front_door_probe_failed") }

$proof = if ($checks.Count -eq 0) { "GO" } else { "NO-GO" }
$evidence = [ordered]@{
    kind = "immoapp_installed_desktop_front_door_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    source_commit_sha = $SourceCommitSha
    installer_sha256 = $InstallerSha256
    installed_exe_path = (Resolve-Path -LiteralPath $InstalledExePath).Path
    installed_exe_sha256 = $installedExeSha
    installed_inventory_path = $InstalledInventoryJson
    installed_inventory_sha256 = $inventorySha
    installed_inventory_exe_sha256 = $inventoryExeSha
    front_door_url = $frontDoor
    health_status = $healthStatus
    identity_status = $identityStatus
    front_door_header = $frontDoorHeader
    identity_kind = $identityKind
    identity_schema_version = $identitySchema
    persisted_config_status = [string]$config.status
    persisted_client_config_path = [string]$config.path
    persisted_client_base_url = $persistedBaseUrl
    connection_source = $connectionSource
    failure_reason = if ($failureReason) { $failureReason } else { ($checks -join ";") }
    proof_result = $proof
}

$outputDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($OutputJson))
$approvedRoot = if ($outputDir) { $outputDir } else { (Get-Location).Path }
Write-ImmoAppSafeJson -Path $OutputJson -Payload $evidence -ApprovedRoots @($approvedRoot) -Depth 8 | Out-Null
Write-Host "Installed desktop front-door evidence JSON: $OutputJson"
Write-Host "Installed desktop front-door proof_result=$proof"
