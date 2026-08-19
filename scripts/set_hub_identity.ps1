param(
    [Parameter(Mandatory = $true)]
    [string]$HubDisplayName,
    [ValidateSet("installer_setup", "installer", "hub_manager", "dev_fixture")]
    [string]$Source = "hub_manager",
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$identity = Write-ImmoAppHubIdentity -HubDisplayName $HubDisplayName -Source $Source
$manifest = Write-ImmoAppHubStateManifest -Source $(if ($Source -eq "hub_manager") { "hub_manager" } else { "installer_setup" })
$result = [ordered]@{
    kind = "immoapp_hub_identity_evidence"
    schema_version = 1
    proof_result = "GO"
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    hub_id = [string]$identity.hub_id
    hub_display_name = $HubDisplayName
    hub_identity_status = [string]$identity.proof_result
    hub_identity_path = [string]$identity.path
    hub_identity_sha256 = [string]$identity.sha256
    hub_state_manifest_status = [string]$manifest.proof_result
    hub_state_manifest_path = [string]$manifest.path
    hub_state_manifest_sha256 = [string]$manifest.sha256
    hostname_mutated = $false
    hub_identity = $identity.hub_identity
    hub_identity_write_result = $identity
    hub_state_manifest = $manifest
}

if ($OutputJson) {
    $paths = Ensure-ImmoAppRuntimeLayout
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $result -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) | Out-Null
}

$result | ConvertTo-Json -Depth 8
