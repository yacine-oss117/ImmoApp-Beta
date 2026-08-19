param(
    [string]$HubBaseUrl = "",
    [string]$OutputJson = "",
    [string]$RuntimeDetectionJson = "",
    [string]$FirewallStatus = "not_configured"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Invoke-JsonHealth {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $response = Invoke-WebRequest -Method Get -Uri $Url -TimeoutSec 8 -UseBasicParsing
        return [ordered]@{
            checked = $true
            url = $Url
            status = [int]$response.StatusCode
            ok = ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 300)
            error = ""
        }
    }
    catch {
        return [ordered]@{
            checked = $true
            url = $Url
            status = $null
            ok = $false
            error = $_.Exception.Message
        }
    }
}

function Get-ComposeRows {
    try {
        Set-ImmoAppHubRuntimeProfileEnv
        $composeFiles = Get-ImmoAppComposeArgs -Names @("compose.yml", "compose.windows.yml")
        $args = (Get-ImmoAppComposeProjectArgs) + @("--env-file", (Get-ImmoAppDefaultEnvFile)) + $composeFiles + @("ps", "--format", "json")
        $raw = Invoke-ImmoAppHubCompose -ComposeArgs $args -NoThrow 2>$null
        if ($LASTEXITCODE -ne 0) {
            return @([ordered]@{ error = "Hub Compose ps failed"; exit_code = $LASTEXITCODE })
        }
        $rows = @()
        foreach ($line in @($raw)) {
            if ([string]::IsNullOrWhiteSpace([string]$line)) { continue }
            $rows += ($line | ConvertFrom-Json)
        }
        return @($rows)
    }
    catch {
        return @([ordered]@{ error = $_.Exception.Message })
    }
}

function Get-UnsafePublishers {
    param([object[]]$Rows)
    $infra = @("db", "rabbitmq", "valkey", "openbao", "minio", "clamav", "web")
    $unsafe = New-Object System.Collections.Generic.List[object]
    foreach ($row in $Rows) {
        $service = [string](Get-ImmoAppObjectValue -Data $row -Name "Service")
        if ([string]::IsNullOrWhiteSpace($service)) {
            $service = [string](Get-ImmoAppObjectValue -Data $row -Name "service")
        }
        $publishers = Get-ImmoAppObjectValue -Data $row -Name "Publishers"
        if ($null -eq $publishers) {
            $publishers = Get-ImmoAppObjectValue -Data $row -Name "publishers"
        }
        foreach ($publisher in @($publishers)) {
            $url = [string](Get-ImmoAppObjectValue -Data $publisher -Name "URL")
            if ([string]::IsNullOrWhiteSpace($url)) {
                $url = [string](Get-ImmoAppObjectValue -Data $publisher -Name "url")
            }
            if ([string]::IsNullOrWhiteSpace($url)) { continue }
            $isLocalOnly = $url -in @("127.0.0.1", "localhost", "::1")
            if ($service -eq "caddy") {
                continue
            }
            if (($infra -contains $service) -and -not $isLocalOnly) {
                $unsafe.Add([ordered]@{
                    service = $service
                    url = $url
                    target_port = Get-ImmoAppObjectValue -Data $publisher -Name "TargetPort"
                    published_port = Get-ImmoAppObjectValue -Data $publisher -Name "PublishedPort"
                    reason = if ($service -eq "web") { "backend_direct_port_lan_exposed" } else { "infra_port_lan_exposed" }
                })
            }
        }
    }
    return @($unsafe.ToArray())
}

function Get-ServiceLanBindStatus {
    param(
        [object[]]$Rows,
        [Parameter(Mandatory = $true)][string]$ServiceName
    )
    foreach ($row in $Rows) {
        $service = [string](Get-ImmoAppObjectValue -Data $row -Name "Service")
        if ([string]::IsNullOrWhiteSpace($service)) {
            $service = [string](Get-ImmoAppObjectValue -Data $row -Name "service")
        }
        if ($service -ne $ServiceName) { continue }
        $publishers = Get-ImmoAppObjectValue -Data $row -Name "Publishers"
        if ($null -eq $publishers) {
            $publishers = Get-ImmoAppObjectValue -Data $row -Name "publishers"
        }
        foreach ($publisher in @($publishers)) {
            $url = [string](Get-ImmoAppObjectValue -Data $publisher -Name "URL")
            if ([string]::IsNullOrWhiteSpace($url)) {
                $url = [string](Get-ImmoAppObjectValue -Data $publisher -Name "url")
            }
            if ([string]::IsNullOrWhiteSpace($url)) { continue }
            if ($url -in @("127.0.0.1", "localhost", "::1")) {
                return "localhost_only"
            }
            return "lan_bound"
        }
        return "not_published"
    }
    return "service_missing"
}

function Test-CaddyAdminLanExposure {
    param([object[]]$Rows)
    foreach ($row in $Rows) {
        $service = [string](Get-ImmoAppObjectValue -Data $row -Name "Service")
        if ([string]::IsNullOrWhiteSpace($service)) {
            $service = [string](Get-ImmoAppObjectValue -Data $row -Name "service")
        }
        if ($service -ne "caddy") { continue }
        $publishers = Get-ImmoAppObjectValue -Data $row -Name "Publishers"
        if ($null -eq $publishers) { $publishers = Get-ImmoAppObjectValue -Data $row -Name "publishers" }
        foreach ($publisher in @($publishers)) {
            $target = [string](Get-ImmoAppObjectValue -Data $publisher -Name "TargetPort")
            $url = [string](Get-ImmoAppObjectValue -Data $publisher -Name "URL")
            if ($target -eq "2019" -and $url -notin @("127.0.0.1", "localhost", "::1")) {
                return $true
            }
        }
    }
    return $false
}

$runtimePaths = Ensure-ImmoAppRuntimeLayout
$runtimeDetectionPath = if ($RuntimeDetectionJson) { $RuntimeDetectionJson } else { Join-Path $runtimePaths.LogsRoot "hub_runtime_detection.json" }
$runtimeDetection = Resolve-ImmoAppHubRuntimeDetection -RuntimeDetectionJson $runtimeDetectionPath
$runtimeProofOnly = ([string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "proof_only")).ToLowerInvariant() -in @("true", "1")
$runtimeAgencyReady = (
    [string]$runtimeDetection.agency_install_status -eq "GO" -and
    [string]$runtimeDetection.provider_validation_status -eq "valid" -and
    [string]$runtimeDetection.reason_code -eq "managed_runtime_ready" -and
    -not $runtimeProofOnly
)
$hubUrl = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { Get-ImmoAppHubBaseUrl -PreferLan }
$health = Invoke-JsonHealth -Url "$($hubUrl.TrimEnd('/'))/api/v1/health/"
$rows = @(Get-ComposeRows)
$unsafePublishers = @(Get-UnsafePublishers -Rows $rows)
$webHealthStatus = if ($health.ok -eq $true) { "reachable" } else { "web_health_unreachable" }
$caddyLanBindStatus = Get-ServiceLanBindStatus -Rows $rows -ServiceName "caddy"
$backendLanBindStatus = Get-ServiceLanBindStatus -Rows $rows -ServiceName "web"
$caddyAdminExposed = Test-CaddyAdminLanExposure -Rows $rows
$infraExposureStatus = if ($unsafePublishers.Count -eq 0) { "internal_only" } else { "lan_exposed" }
$boundaryResult = if ($health.ok -eq $true -and $unsafePublishers.Count -eq 0 -and -not $caddyAdminExposed) { "GO" } else { "NO-GO" }
$reasonCode = if ($unsafePublishers.Count -gt 0) {
    "infra_exposed"
} elseif ($caddyAdminExposed) {
    "caddy_admin_exposed"
} elseif ($health.ok -ne $true) {
    "web_health_unreachable"
} else {
    "boundary_ok"
}
$reason = if ($boundaryResult -eq "GO") {
    ""
} else {
    $parts = @()
    if ($health.ok -ne $true) { $parts += "web_health_unreachable" }
    if ($unsafePublishers.Count -gt 0) { $parts += "unsafe_lan_publishers" }
    if ($caddyAdminExposed) { $parts += "caddy_admin_exposed" }
    $parts -join "; "
}

$evidence = [ordered]@{
    kind = "immoapp_hub_network_boundary_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    hub_base_url = $hubUrl
    front_door_url = $hubUrl
    proof_scope = "local_compose_boundary"
    external_lan_probe_performed = $false
    external_lan_probe_required_for_real_lan_go = $true
    proof_result = $boundaryResult
    failure_reason = $reason
    agency_install_status = if ($boundaryResult -eq "GO" -and $runtimeAgencyReady) { "GO" } else { "NO_GO" }
    reason_code = $reasonCode
    boundary_result = $boundaryResult
    runtime_detection = $runtimeDetection
    web_api_health = $health
    web_api_health_status = $webHealthStatus
    web_api_lan_bind_status = $caddyLanBindStatus
    caddy_status = $caddyLanBindStatus
    caddy_admin_lan_exposed = $caddyAdminExposed
    backend_internal_status = $backendLanBindStatus
    infra_exposure_status = $infraExposureStatus
    exposed_infra_services = @($unsafePublishers)
    firewall_status = $FirewallStatus
    approved_lan_facing_service = "caddy"
    approved_lan_facing_port = Get-ImmoAppHubPort
    infra_ports_policy = "localhost_or_internal_only"
    unsafe_publishers = $unsafePublishers
    compose_services = $rows
}

if ($OutputJson) {
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $evidence -ApprovedRoots @($runtimePaths.LogsRoot, $runtimePaths.ConfigRoot, $runtimePaths.TmpRoot) | Out-Null
}

$evidence | ConvertTo-Json -Depth 12
if ($evidence.proof_result -ne "GO") {
    exit 1
}
