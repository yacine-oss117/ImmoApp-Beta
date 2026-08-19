param(
    [int]$Port = 41900,
    [int]$IntervalSeconds = 5,
    [switch]$Once,
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
    app_version = $env:IMMOAPP_CLIENT_VERSION
    api_version = if ($env:IMMOAPP_API_VERSION) { $env:IMMOAPP_API_VERSION } else { "v1" }
    machine_hostname_readonly = $env:COMPUTERNAME
}
$json = $payload | ConvertTo-Json -Depth 6 -Compress
$bytes = [System.Text.Encoding]::UTF8.GetBytes($json)

$sent = 0
$client = [System.Net.Sockets.UdpClient]::new()
try {
    $client.EnableBroadcast = $true
    $endpoint = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Broadcast, $Port)
    do {
        [void]$client.Send($bytes, $bytes.Length, $endpoint)
        $sent += 1
        if ($Once) { break }
        Start-Sleep -Seconds ([Math]::Max(1, $IntervalSeconds))
    } while ($true)
}
finally {
    $client.Dispose()
}

$result = [ordered]@{
    kind = "immoapp_hub_discovery_beacon_result"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    proof_result = "GO"
    sent_count = $sent
    discovery_payload = $payload
    contains_secrets = $false
}
if ($OutputJson) {
    $paths = Ensure-ImmoAppRuntimeLayout
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $result -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) | Out-Null
}
$result | ConvertTo-Json -Depth 8
