param(
    [Parameter(Mandatory = $true)]
    [string]$HubBaseUrl,
    [string]$ExpectedBackendIdentity = "",
    [string]$OutputJson = "",
    [switch]$RequireWorkstationUrl,
    [int]$ExpectedHealthStatus = 200
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Join-UrlPath {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$Path
    )
    return $BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

function Get-DnsResolutionSummary {
    param([Parameter(Mandatory = $true)][string]$HostName)
    $addresses = @()
    try {
        $addresses = @([System.Net.Dns]::GetHostAddresses($HostName) |
            ForEach-Object { $_.IPAddressToString } |
            Sort-Object -Unique)
    }
    catch {
        return [ordered]@{
            host = $HostName
            ok = $false
            error = $_.Exception.Message
            addresses = @()
        }
    }
    return [ordered]@{
        host = $HostName
        ok = ($addresses.Count -gt 0)
        error = $null
        addresses = @($addresses)
    }
}

function Get-NetworkAdapterSummary {
    $adapters = @()
    try {
        $adapters = Get-NetAdapter -Physical -ErrorAction Stop |
            Where-Object { $_.Status -eq "Up" } |
            Select-Object -First 8 Name, InterfaceDescription, Status, LinkSpeed
    }
    catch {
        return @([ordered]@{
                source = "Get-NetAdapter"
                error = $_.Exception.Message
            })
    }
    return @($adapters)
}

function Test-LocalhostUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    try { $uri = [Uri]$Url } catch { return $false }
    return $uri.Host.Trim().ToLowerInvariant() -in @("localhost", "127.0.0.1", "::1")
}

function Test-TcpConnectivity {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne([TimeSpan]::FromSeconds(5))
        if (-not $ok) {
            return [ordered]@{ host = $HostName; port = $Port; ok = $false; error = "timeout" }
        }
        $client.EndConnect($async)
        return [ordered]@{ host = $HostName; port = $Port; ok = $true; error = $null }
    }
    catch {
        return [ordered]@{ host = $HostName; port = $Port; ok = $false; error = $_.Exception.Message }
    }
    finally {
        $client.Dispose()
    }
}

function Get-ConnectionFailureReason {
    param([Parameter(Mandatory = $true)][System.Exception]$Exception)
    $message = $Exception.Message
    if ($message -match "No such host|The remote name could not be resolved|NameResolutionFailure") {
        return "DNS failure: $message"
    }
    if ($message -match "actively refused|Connection refused") {
        return "Connection refused: $message"
    }
    if ($message -match "timed out|timeout") {
        return "Timeout: $message"
    }
    if ($message -match "certificate|SSL|TLS|trust") {
        return "TLS/certificate failure: $message"
    }
    return $message
}

$normalizedBaseUrl = $HubBaseUrl.Trim().TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($normalizedBaseUrl)) {
    throw "HubBaseUrl is required."
}

try {
    $hubUri = [Uri]$normalizedBaseUrl
}
catch {
    throw "HubBaseUrl is not a valid absolute URL: $HubBaseUrl"
}
if (-not $hubUri.IsAbsoluteUri -or $hubUri.Scheme -notin @("http", "https")) {
    throw "HubBaseUrl must be an absolute http or https URL: $HubBaseUrl"
}
if ($RequireWorkstationUrl.IsPresent -and (Test-LocalhostUrl -Url $normalizedBaseUrl)) {
    throw "HubBaseUrl cannot be localhost when -RequireWorkstationUrl is used for workstation LAN proof."
}

$healthUrl = Join-UrlPath -BaseUrl $normalizedBaseUrl -Path "/api/v1/health/"
$identityUrl = Join-UrlPath -BaseUrl $normalizedBaseUrl -Path "/api/v1/hub/front-door/identity/"
Write-Host "Testing Hub URL from this workstation/profile: $normalizedBaseUrl"

$dns = Get-DnsResolutionSummary -HostName $hubUri.Host
$port = if ($hubUri.Port -gt 0) { $hubUri.Port } elseif ($hubUri.Scheme -eq "https") { 443 } else { 80 }
$tcp = Test-TcpConnectivity -HostName $hubUri.Host -Port $port
$identityStatus = [ordered]@{
    checked = $false
    status = $null
    matched_expected = $null
    error = $null
}

try {
    $healthResponse = Invoke-WebRequest -Method Get -Uri $healthUrl -TimeoutSec 8 -UseBasicParsing
}
catch {
    throw "LAN reachability health check failed at $healthUrl. $(Get-ConnectionFailureReason -Exception $_.Exception)"
}

$healthStatus = [int]$healthResponse.StatusCode
if ($healthStatus -ne $ExpectedHealthStatus) {
    throw "LAN reachability health check returned HTTP $healthStatus at $healthUrl, expected $ExpectedHealthStatus."
}

try {
    $identityResponse = Invoke-WebRequest -Method Get -Uri $identityUrl -TimeoutSec 5 -UseBasicParsing
    $identityStatus.checked = $true
    $identityStatus.status = [int]$identityResponse.StatusCode
    $frontDoorHeader = [string]$identityResponse.Headers["X-ImmoApp-Front-Door"]
    if ($frontDoorHeader.ToLowerInvariant() -ne "caddy") {
        throw "Hub URL did not respond through the Caddy front door."
    }
    if ($ExpectedBackendIdentity) {
        $identityStatus.matched_expected = ($identityResponse.Content -match [regex]::Escape($ExpectedBackendIdentity))
        if (-not $identityStatus.matched_expected) {
            throw "Backend identity response did not include expected identity token."
        }
    }
}
catch {
    if ($ExpectedBackendIdentity) {
        throw "Expected backend identity proof failed at $identityUrl. $($_.Exception.Message)"
    }
    $identityStatus.checked = $true
    $identityStatus.error = $_.Exception.Message
}

$proof = [ordered]@{
    kind = "immoapp_lan_workstation_reachability_proof"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    hub_base_url = $normalizedBaseUrl
    backend_url_is_localhost = Test-LocalhostUrl -Url $normalizedBaseUrl
    is_workstation_candidate = (-not (Test-LocalhostUrl -Url $normalizedBaseUrl))
    health_url = $healthUrl
    health_status = $healthStatus
    expected_health_status = $ExpectedHealthStatus
    tcp_connectivity_result = $tcp
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    dns_resolution = $dns
    network_adapters = Get-NetworkAdapterSummary
    network_adapter_summary = Get-NetworkAdapterSummary
    identity_endpoint = $identityUrl
    identity_status = $identityStatus
    mutation_routes_used = $false
}

if ($OutputJson) {
    $outputDir = Split-Path -Parent $OutputJson
    if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir | Out-Null
    }
    $proof | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
    Write-Host "LAN reachability proof JSON: $OutputJson"
}

Write-Host "LAN reachability health_status=$healthStatus"
Write-Host "LAN reachability mutation_routes_used=false"
