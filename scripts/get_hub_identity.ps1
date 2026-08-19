param(
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$identity = Read-ImmoAppHubIdentity
$result = [ordered]@{
    kind = "immoapp_hub_identity_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    proof_result = "GO"
    path = $identity.path
    path_safe = $true
    hub_identity = $identity.data
    hub_display_name = $identity.hub_display_name
    machine_hostname_readonly = $identity.data.machine_hostname_readonly
    hostname_mutated = $false
}

if ($OutputJson) {
    $paths = Ensure-ImmoAppRuntimeLayout
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $result -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) | Out-Null
}

$result | ConvertTo-Json -Depth 8
