param(
    [Parameter(Mandatory = $true)][string]$HubBaseUrl,
    [Parameter(Mandatory = $true)][string]$ReachabilityProofJson,
    [Parameter(Mandatory = $true)][string]$InstallerSha256,
    [Parameter(Mandatory = $true)][string]$SourceCommitSha,
    [Parameter(Mandatory = $true)][string]$DesktopBackendUrl,
    [Parameter(Mandatory = $true)][string]$SupportBundlePath,
    [Parameter(Mandatory = $true)][string]$OutputJson,
    [string]$HubMachineName = "not_recorded",
    [string]$NetworkType = "not_recorded",
    [string]$WindowsFirewallRuleStatus = "not_verified",
    [switch]$OwnerLoginConfirmed,
    [switch]$CrudConfirmed,
    [switch]$OfferPhotoThumbnailConfirmed,
    [switch]$HubBackupRestoreConfirmed,
    [switch]$UninstallReinstallConfirmed,
    [string]$UninstallReinstallDeferredWithReason = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-LocalhostUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    try { $uri = [Uri]$Url } catch { return $false }
    return $uri.Host.Trim().ToLowerInvariant() -in @("localhost", "127.0.0.1", "::1")
}

if (Test-LocalhostUrl -Url $HubBaseUrl) {
    throw "LAN workstation evidence requires a Hub IP/hostname URL, not localhost."
}
if (Test-LocalhostUrl -Url $DesktopBackendUrl) {
    throw "LAN workstation evidence rejects localhost desktop_backend_url."
}
if ([string]::IsNullOrWhiteSpace($SourceCommitSha)) {
    throw "LAN workstation evidence requires source commit SHA."
}
if ([string]::IsNullOrWhiteSpace($InstallerSha256)) {
    throw "LAN workstation evidence requires installer SHA-256."
}
foreach ($name in @("OwnerLoginConfirmed", "CrudConfirmed", "OfferPhotoThumbnailConfirmed", "HubBackupRestoreConfirmed")) {
    if (-not (Get-Variable -Name $name -ValueOnly).IsPresent) {
        throw "LAN workstation evidence requires explicit -$name after that proof was actually observed."
    }
}
if (-not $UninstallReinstallConfirmed.IsPresent -and [string]::IsNullOrWhiteSpace($UninstallReinstallDeferredWithReason)) {
    throw "LAN workstation evidence requires -UninstallReinstallConfirmed or -UninstallReinstallDeferredWithReason."
}
if (-not (Test-Path -LiteralPath $ReachabilityProofJson)) {
    throw "Reachability proof JSON not found: $ReachabilityProofJson"
}
if (-not (Test-Path -LiteralPath $SupportBundlePath)) {
    throw "Workstation support bundle path not found: $SupportBundlePath"
}
$reachability = Get-Content -LiteralPath $ReachabilityProofJson -Raw | ConvertFrom-Json
if ([string]$reachability.kind -ne "immoapp_lan_workstation_reachability_proof") {
    throw "Reachability proof has wrong kind."
}
if ([int]$reachability.health_status -ne 200) {
    throw "Reachability proof health_status must be 200."
}
if ([string]$reachability.hub_base_url -ne $HubBaseUrl.TrimEnd("/")) {
    throw "Reachability proof hub_base_url does not match HubBaseUrl."
}

$evidence = [ordered]@{
    kind = "immoapp_lan_hub_workstation_evidence"
    schema_version = 2
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    source_commit_sha = $SourceCommitSha
    installer_sha256 = $InstallerSha256.ToLowerInvariant()
    hub_machine_name = if ($HubMachineName) { $HubMachineName } else { "not_recorded" }
    workstation_machine_or_profile_name = $env:COMPUTERNAME
    hub_base_url = $HubBaseUrl.TrimEnd("/")
    desktop_backend_url = $DesktopBackendUrl.TrimEnd("/")
    backend_url_is_localhost = Test-LocalhostUrl -Url $DesktopBackendUrl
    reachability_proof_path = (Resolve-Path -LiteralPath $ReachabilityProofJson).Path
    reachability_proof_sha256 = Get-FileSha256 -Path $ReachabilityProofJson
    reachability_proof = $reachability
    health_status = [int]$reachability.health_status
    network_type = $NetworkType
    windows_firewall_rule_status = $WindowsFirewallRuleStatus
    owner_login_proof = $OwnerLoginConfirmed.IsPresent
    workstation_create_read_update_proof = $CrudConfirmed.IsPresent
    workstation_offer_photo_thumbnail_proof = $OfferPhotoThumbnailConfirmed.IsPresent
    workstation_support_bundle_path = (Resolve-Path -LiteralPath $SupportBundlePath).Path
    workstation_support_bundle_sha256 = Get-FileSha256 -Path $SupportBundlePath
    hub_backup_restore_proof = $HubBackupRestoreConfirmed.IsPresent
    uninstall_reinstall_behavior = if ($UninstallReinstallConfirmed.IsPresent) { "confirmed" } else { "deferred: $UninstallReinstallDeferredWithReason" }
    remote_evidence = $false
    mutation_routes_used = $false
}

$outputDir = Split-Path -Parent $OutputJson
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
$evidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
Write-Host "LAN workstation evidence JSON: $OutputJson"
Write-Host "LAN workstation health_status=$($evidence.health_status)"
Write-Host "LAN workstation mutation_routes_used=false"
