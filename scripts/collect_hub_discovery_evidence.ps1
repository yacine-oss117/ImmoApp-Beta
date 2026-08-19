param(
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$identity = Read-ImmoAppHubIdentity
$frontDoorUrl = Get-ImmoAppHubBaseUrl -PreferLan
$payload = [ordered]@{
    kind = "immoapp_hub_discovery"
    schema_version = 1
    hub_display_name = $identity.hub_display_name
    front_door_url = $frontDoorUrl
    front_door_port = [int](Get-ImmoAppHubPort)
    protocol = "http"
    health_path = "/api/v1/health/"
    api_version = if ($env:IMMOAPP_API_VERSION) { $env:IMMOAPP_API_VERSION } else { "v1" }
    machine_hostname_readonly = $env:COMPUTERNAME
}

$evidence = [ordered]@{
    kind = "immoapp_hub_discovery_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    proof_result = "NO-GO"
    reason_code = "local_discovery_proof_only"
    proof_scope = "local_internal"
    external_lan_probe_performed = $false
    external_lan_probe_required_for_real_lan_go = $true
    discovery_payload = $payload
    advertised_display_name = $identity.hub_display_name
    advertised_front_door_url = $frontDoorUrl
    secrets_advertised = $false
    internal_ports_advertised = $false
    agency_install_status = "NO_GO"
}

if ($OutputJson) {
    $paths = Ensure-ImmoAppRuntimeLayout
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $evidence -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) | Out-Null
}

$evidence | ConvertTo-Json -Depth 8
exit 1
