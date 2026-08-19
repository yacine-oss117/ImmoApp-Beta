param(
    [string]$HubBaseUrl = "",
    [Parameter(Mandatory = $true)][string]$OutputJson,
    [string]$SourceCommitSha = "",
    [string]$InstallerSha256 = "",
    [string]$InstalledVersion = "",
    [string]$InstalledBuildIdentityJson = "",
    [string]$RuntimeDetectionJson = "",
    [string]$RuntimeDependencyMode = "",
    [string]$AgencyInstallStatus = "",
    [string]$WindowsFirewallRuleStatus = "not_verified"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Get-ObjectValue {
    param(
        [object]$Data,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $Data) { return $null }
    if ($Data -is [System.Collections.IDictionary] -and $Data.Contains($Name)) {
        return $Data[$Name]
    }
    $property = $Data.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-HubRuntimeDetection {
    param([Parameter(Mandatory = $true)][string]$OutputJson)
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") -OutputJson $OutputJson
    if ($LASTEXITCODE -ne 0) { throw "Hub runtime detection failed." }
    return (($output | Out-String) | ConvertFrom-Json)
}

function Get-GitCommitSha {
    if ($SourceCommitSha) { return $SourceCommitSha }
    try {
        $repoRoot = (Get-ImmoAppRepoRoot).Path
        $sha = (& git -C $repoRoot rev-parse HEAD 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $sha) { return $sha }
    }
    catch {
        return ""
    }
    return ""
}

function Invoke-JsonRequest {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $response = Invoke-WebRequest -Method Get -Uri $Url -TimeoutSec 8 -UseBasicParsing
        $body = [string]$response.Content
        $parsed = $null
        try { $parsed = $body | ConvertFrom-Json } catch { $parsed = $null }
        return [ordered]@{
            checked = $true
            url = $Url
            status = [int]$response.StatusCode
            ok = ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 300)
            body = $parsed
            error = $null
        }
    }
    catch {
        return [ordered]@{
            checked = $true
            url = $Url
            status = $null
            ok = $false
            body = $null
            error = $_.Exception.Message
        }
    }
}

function Get-ComposeServiceStatus {
    $services = @()
    try {
        Set-ImmoAppHubRuntimeProfileEnv
        $composeFiles = Get-ImmoAppComposeArgs -Names @("compose.yml", "compose.windows.yml")
        $args = (Get-ImmoAppComposeProjectArgs) + @("--env-file", (Get-ImmoAppDefaultEnvFile)) + $composeFiles + @("ps", "--format", "json")
        $output = Invoke-ImmoAppHubCompose -ComposeArgs $args -NoThrow 2>$null
        if ($LASTEXITCODE -ne 0) {
            return @([ordered]@{ error = "Hub Compose ps failed"; exit_code = $LASTEXITCODE })
        }
        foreach ($line in @($output)) {
            if ([string]::IsNullOrWhiteSpace([string]$line)) { continue }
            try {
                $entry = $line | ConvertFrom-Json
                $services += [ordered]@{
                    name = [string]$entry.Name
                    service = [string]$entry.Service
                    state = [string]$entry.State
                    health = [string]$entry.Health
                    published_ports = [string]$entry.Publishers
                }
            }
            catch {
                $services += [ordered]@{ raw = [string]$line; parse_error = $_.Exception.Message }
            }
        }
    }
    catch {
        $services = @([ordered]@{ error = $_.Exception.Message })
    }
    return @($services)
}

function Get-StatusForServices {
    param(
        [Parameter(Mandatory = $true)][object[]]$Services,
        [Parameter(Mandatory = $true)][string[]]$Names
    )
    foreach ($name in $Names) {
        $entry = $null
        foreach ($candidate in $Services) {
            if ([string](Get-ObjectValue -Data $candidate -Name "service") -eq $name) {
                $entry = $candidate
                break
            }
        }
        if ($null -eq $entry) { continue }
        $state = [string]$entry.state
        $health = [string]$entry.health
        if ($state -eq "running" -and ($health -eq "healthy" -or [string]::IsNullOrWhiteSpace($health))) {
            return "ok"
        }
        return "error"
    }
    return "unknown"
}

function Get-ServiceHealthSummary {
    param([object[]]$Services)
    return [ordered]@{
        api = Get-StatusForServices -Services $Services -Names @("web")
        database = Get-StatusForServices -Services $Services -Names @("db")
        storage_photos = Get-StatusForServices -Services $Services -Names @("minio")
        worker = Get-StatusForServices -Services $Services -Names @("worker", "worker-import", "worker-match", "worker-rebuild", "beat")
    }
}

function Test-ManagedWsl2ArtifactRuntimeReady {
    param([object]$RuntimeDetection)
    return (
        [string](Get-ObjectValue -Data $RuntimeDetection -Name "runtime_dependency_mode") -eq "managed_wsl2_container_runtime_artifact" -and
        [string](Get-ObjectValue -Data $RuntimeDetection -Name "provider_validation_status") -eq "valid" -and
        [string](Get-ObjectValue -Data $RuntimeDetection -Name "internal_proof_status") -eq "GO" -and
        [string](Get-ObjectValue -Data $RuntimeDetection -Name "runtime_artifact_status") -eq "GO" -and
        [string](Get-ObjectValue -Data $RuntimeDetection -Name "runtime_start_status") -eq "GO" -and
        [string](Get-ObjectValue -Data $RuntimeDetection -Name "front_door_health_status") -eq "GO"
    )
}

function Import-ManagedWsl2StartEvidence {
    param([object]$RuntimeDetection)
    $path = [string](Get-ObjectValue -Data $RuntimeDetection -Name "runtime_start_evidence_path")
    if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return $null
    }
    $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if (
        [string](Get-ObjectValue -Data $data -Name "kind") -ne "immoapp_managed_wsl2_runtime_start_evidence" -or
        [string](Get-ObjectValue -Data $data -Name "proof_result") -ne "GO" -or
        [string](Get-ObjectValue -Data $data -Name "runtime_command_status") -ne "GO" -or
        [string](Get-ObjectValue -Data $data -Name "compose_service_status") -ne "GO" -or
        [string](Get-ObjectValue -Data $data -Name "front_door_health_status") -ne "GO"
    ) {
        return $null
    }
    return $data
}

function Get-ManagedWsl2ArtifactServiceStatus {
    param([object]$StartEvidence)
    $services = @()
    foreach ($entry in @($StartEvidence.services)) {
        $name = [string](Get-ObjectValue -Data $entry -Name "name")
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $services += [ordered]@{
            name = $name
            service = $name
            state = [string](Get-ObjectValue -Data $entry -Name "state")
            health = [string](Get-ObjectValue -Data $entry -Name "health")
            managed_runtime_status = [string](Get-ObjectValue -Data $entry -Name "status")
            published_ports = ""
        }
    }
    return @($services)
}

function Get-FailingComposeServices {
    param([object[]]$Services)
    $expected = Get-ImmoAppHubRequiredComposeServices
    $seen = @{}
    $failures = New-Object System.Collections.Generic.List[object]
    foreach ($entry in $Services) {
        $error = [string](Get-ObjectValue -Data $entry -Name "error")
        if ($error) {
            $failures.Add([ordered]@{ service = "compose"; state = "error"; health = ""; reason = $error })
            continue
        }
        $service = [string](Get-ObjectValue -Data $entry -Name "service")
        if ([string]::IsNullOrWhiteSpace($service)) { continue }
        $seen[$service] = $true
        $state = [string](Get-ObjectValue -Data $entry -Name "state")
        $health = [string](Get-ObjectValue -Data $entry -Name "health")
        if ($state -ne "running" -or (-not [string]::IsNullOrWhiteSpace($health) -and $health -ne "healthy")) {
            $failures.Add([ordered]@{
                service = $service
                container = [string](Get-ObjectValue -Data $entry -Name "name")
                state = $state
                health = $health
                reason = "service_not_ready"
            })
        }
    }
    foreach ($name in $expected) {
        if (-not $seen.ContainsKey($name)) {
            $failures.Add([ordered]@{ service = $name; container = ""; state = "missing"; health = ""; reason = "service_missing" })
        }
    }
    return @($failures.ToArray())
}

function Get-MissingComposeServices {
    param([object[]]$Services)
    $seen = @{}
    foreach ($entry in $Services) {
        $service = [string](Get-ObjectValue -Data $entry -Name "service")
        if (-not [string]::IsNullOrWhiteSpace($service)) {
            $seen[$service] = $true
        }
    }
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($service in (Get-ImmoAppHubRequiredComposeServices)) {
        if (-not $seen.ContainsKey($service)) {
            $missing.Add($service)
        }
    }
    return @($missing.ToArray())
}

function Get-StartingComposeServices {
    param([object[]]$Services)
    $starting = New-Object System.Collections.Generic.List[object]
    foreach ($entry in $Services) {
        $service = [string](Get-ObjectValue -Data $entry -Name "service")
        if ([string]::IsNullOrWhiteSpace($service)) { continue }
        $state = ([string](Get-ObjectValue -Data $entry -Name "state")).ToLowerInvariant()
        $health = ([string](Get-ObjectValue -Data $entry -Name "health")).ToLowerInvariant()
        if ($state -in @("created", "restarting") -or $health -eq "starting") {
            $starting.Add([ordered]@{
                service = $service
                container = [string](Get-ObjectValue -Data $entry -Name "name")
                state = $state
                health = $health
            })
        }
    }
    return @($starting.ToArray())
}

function Resolve-RuntimeState {
    param([object]$RuntimeDetection)
    $mode = [string](Get-ObjectValue -Data $RuntimeDetection -Name "runtime_dependency_mode")
    $engine = [string](Get-ObjectValue -Data $RuntimeDetection -Name "docker_engine_reachable")
    $compose = [string](Get-ObjectValue -Data $RuntimeDetection -Name "compose_available")
    $status = [string](Get-ObjectValue -Data $RuntimeDetection -Name "agency_install_status")
    if ($mode -eq "managed_container_runtime" -and $status -eq "GO") {
        return "available_managed"
    }
    if ($mode -eq "manual_docker_desktop" -and $engine -in @("True", "true", "1") -and $compose -in @("True", "true", "1")) {
        return "available_internal_no_go"
    }
    if (
        $mode -eq "managed_wsl2_container_runtime_candidate" -and
        [string](Get-ObjectValue -Data $RuntimeDetection -Name "provider_validation_status") -eq "valid" -and
        [string](Get-ObjectValue -Data $RuntimeDetection -Name "internal_proof_status") -eq "GO"
    ) {
        return "available_internal_wsl2_candidate_no_go"
    }
    if (Test-ManagedWsl2ArtifactRuntimeReady -RuntimeDetection $RuntimeDetection) {
        return "available_internal_wsl2_artifact_no_go"
    }
    return "runtime_unavailable"
}

function Resolve-ComposeState {
    param(
        [object[]]$Services,
        [string[]]$MissingServices,
        [object[]]$StartingServices,
        [object[]]$FailingServices
    )
    $composeErrors = @($Services | Where-Object { [string](Get-ObjectValue -Data $_ -Name "error") })
    if ($composeErrors.Count -gt 0) {
        return "compose_unavailable"
    }
    $requiredCount = (Get-ImmoAppHubRequiredComposeServices).Count
    if ($MissingServices.Count -ge $requiredCount) {
        return "stack_stopped"
    }
    if ($MissingServices.Count -gt 0) {
        return "partial_stack_required_services_missing"
    }
    if ($StartingServices.Count -gt 0) {
        return "stack_starting"
    }
    if ($FailingServices.Count -gt 0) {
        return "service_unhealthy"
    }
    return "running"
}

function Resolve-StatusReasonCode {
    param(
        [bool]$HubOnline,
        [string]$RuntimeState,
        [string]$ComposeState,
        [object]$Health
    )
    if ($HubOnline) { return "online" }
    if ($RuntimeState -eq "runtime_unavailable") { return "runtime_unavailable" }
    if ($ComposeState -eq "partial_stack_required_services_missing") { return "service_missing" }
    if ($ComposeState -in @("stack_stopped", "stack_starting", "service_unhealthy")) {
        return $ComposeState
    }
    if ($ComposeState -eq "compose_unavailable") { return "runtime_unavailable" }
    $healthError = [string](Get-ObjectValue -Data $Health -Name "error")
    if ($healthError -match "timed out|unable to connect|actively refused|No connection") {
        return "health_endpoint_unreachable"
    }
    return "health_endpoint_failed"
}

function Resolve-HubStatus {
    param(
        [bool]$HubOnline,
        [object[]]$Services,
        [string]$ComposeState
    )
    if ($HubOnline) { return "Online" }
    if ($ComposeState -eq "stack_starting") { return "Starting" }
    if ($ComposeState -in @("stack_stopped", "partial_stack_required_services_missing")) { return "Offline" }
    $web = $null
    foreach ($entry in $Services) {
        if ([string](Get-ObjectValue -Data $entry -Name "service") -eq "web") {
            $web = $entry
            break
        }
    }
    if ($null -eq $web) { return "Offline" }
    $state = [string](Get-ObjectValue -Data $web -Name "state")
    $health = [string](Get-ObjectValue -Data $web -Name "health")
    if ($state -in @("created", "restarting") -or $health -eq "starting") { return "Starting" }
    return "Error"
}

function Get-LastBackupSummary {
    $paths = Get-ImmoAppRuntimePaths
    $candidates = @()
    foreach ($root in @($paths.BackupsRoot, $paths.DataAppBackupsRoot)) {
        if (Test-Path -LiteralPath $root) {
            $candidates += @(Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '\.(zip|dump|json)$' } |
                Sort-Object LastWriteTimeUtc -Descending)
        }
    }
    $latest = @($candidates | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1)
    if ($latest.Count -eq 0) {
        return [ordered]@{ status = "missing"; last_backup_path = ""; last_backup_at_utc = ""; last_backup_sha256 = "" }
    }
    return [ordered]@{
        status = "present"
        last_backup_path = $latest[0].FullName
        last_backup_at_utc = $latest[0].LastWriteTimeUtc.ToString("o")
        last_backup_sha256 = Get-FileSha256 -Path $latest[0].FullName
    }
}

function Get-ManagedRuntimeLogRetentionSummary {
    $paths = Get-ImmoAppRuntimePaths
    $path = Join-Path $paths.LogsRoot "managed_runtime_log_retention.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [ordered]@{ exists = $false; path = $path }
    }
    try {
        $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        return [ordered]@{
            exists = $true
            path = $path
            proof_result = [string](Get-ObjectValue -Data $data -Name "proof_result")
            reason_code = [string](Get-ObjectValue -Data $data -Name "reason_code")
            retention_days = [int](Get-ObjectValue -Data $data -Name "retention_days")
            max_total_bytes = [Int64](Get-ObjectValue -Data $data -Name "max_total_bytes")
            scanned_file_count = [int](Get-ObjectValue -Data $data -Name "scanned_file_count")
            deleted_file_count = [int](Get-ObjectValue -Data $data -Name "deleted_file_count")
            deleted_bytes = [Int64](Get-ObjectValue -Data $data -Name "deleted_bytes")
            retained_bytes = [Int64](Get-ObjectValue -Data $data -Name "retained_bytes")
            skipped_file_count = [int](Get-ObjectValue -Data $data -Name "skipped_file_count")
            agency_install_status = [string](Get-ObjectValue -Data $data -Name "agency_install_status")
        }
    }
    catch {
        return [ordered]@{
            exists = $true
            path = $path
            read_error = $_.Exception.GetType().Name
        }
    }
}

$runtimePaths = Ensure-ImmoAppRuntimeLayout
$envFile = Get-ImmoAppDefaultEnvFile
$envValues = Read-ImmoAppEnvFile -Path $envFile
$runtimeDetectionPath = if ($RuntimeDetectionJson) { $RuntimeDetectionJson } else { Join-Path $runtimePaths.LogsRoot "hub_runtime_detection.json" }
$runtimeDetection = if (Test-Path -LiteralPath $runtimeDetectionPath) {
    Get-Content -LiteralPath $runtimeDetectionPath -Raw | ConvertFrom-Json
} else {
    Invoke-HubRuntimeDetection -OutputJson $runtimeDetectionPath
}
if ([string]::IsNullOrWhiteSpace($RuntimeDependencyMode)) {
    $RuntimeDependencyMode = [string]$runtimeDetection.runtime_dependency_mode
}
if ([string]::IsNullOrWhiteSpace($AgencyInstallStatus)) {
    $AgencyInstallStatus = [string]$runtimeDetection.agency_install_status
}
$hubUrl = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { Get-ImmoAppHubBaseUrl -PreferLan }
$profileSummary = $null
try {
    $profileText = Invoke-ImmoAppHubRuntimeProfile -Action "print" -Format "json"
    $profileSummary = ($profileText | Out-String) | ConvertFrom-Json
}
catch {
    $profileSummary = [ordered]@{ error = $_.Exception.Message }
}

$health = Invoke-JsonRequest -Url "$($hubUrl.TrimEnd('/'))/api/v1/health/"
$ready = Invoke-JsonRequest -Url "$($hubUrl.TrimEnd('/'))/api/v1/health/ready/"
$managedWsl2StartEvidence = $null
if (Test-ManagedWsl2ArtifactRuntimeReady -RuntimeDetection $runtimeDetection) {
    $managedWsl2StartEvidence = Import-ManagedWsl2StartEvidence -RuntimeDetection $runtimeDetection
}
$services = if ($managedWsl2StartEvidence) {
    @(Get-ManagedWsl2ArtifactServiceStatus -StartEvidence $managedWsl2StartEvidence)
}
else {
    @(Get-ComposeServiceStatus)
}
$serviceHealth = Get-ServiceHealthSummary -Services $services
$failingServices = @(Get-FailingComposeServices -Services $services)
$missingServices = @(Get-MissingComposeServices -Services $services)
$startingServices = @(Get-StartingComposeServices -Services $services)
$runtimeState = Resolve-RuntimeState -RuntimeDetection $runtimeDetection
$composeState = Resolve-ComposeState -Services $services -MissingServices $missingServices -StartingServices $startingServices -FailingServices $failingServices
$backup = Get-LastBackupSummary
$managedRuntimeLogRetention = Get-ManagedRuntimeLogRetentionSummary
$hubIdentity = $null
try { $hubIdentity = Read-ImmoAppHubIdentity -Optional } catch { $hubIdentity = $null }
$hubState = Get-ImmoAppHubStateSummary
$hubDisplayName = if ($hubIdentity) { [string]$hubIdentity.hub_display_name } else { "" }
$bindHost = if ($env:IMMOAPP_WEB_BIND_HOST) { $env:IMMOAPP_WEB_BIND_HOST } elseif ($envValues.ContainsKey("IMMOAPP_WEB_BIND_HOST")) { [string]$envValues["IMMOAPP_WEB_BIND_HOST"] } else { "127.0.0.1" }
$lanIp = Get-ImmoAppPreferredLanAddress
$installedIdentity = $null
if ($InstalledBuildIdentityJson) {
    if (-not (Test-Path -LiteralPath $InstalledBuildIdentityJson)) {
        throw "Installed build identity JSON not found: $InstalledBuildIdentityJson"
    }
    $installedIdentity = Get-Content -LiteralPath $InstalledBuildIdentityJson -Raw | ConvertFrom-Json
}

$hubOnline = ($health.ok -eq $true -and $serviceHealth.api -eq "ok")
$statusReasonCode = Resolve-StatusReasonCode -HubOnline $hubOnline -RuntimeState $runtimeState -ComposeState $composeState -Health $health
$proofResult = if ($hubOnline) { "GO" } else { "NO-GO" }
$failureReason = if ($hubOnline) {
    ""
} else {
    $failingNames = ((@($failingServices | ForEach-Object { [string](Get-ObjectValue -Data $_ -Name "service") }) | Where-Object { $_ } | Select-Object -Unique) -join ", ")
    $missingNames = (($missingServices | Select-Object -Unique) -join ", ")
    "Hub status is $statusReasonCode. compose_state=$composeState runtime_state=$runtimeState missing_services=$missingNames failing_services=$failingNames"
}

$evidence = [ordered]@{
    kind = "immoapp_hub_status_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    source_commit_sha = Get-GitCommitSha
    installer_sha256 = $InstallerSha256.ToLowerInvariant()
    installed_version = $InstalledVersion
    installed_build_identity = $installedIdentity
    proof_result = $proofResult
    failure_reason = $failureReason
    hub_id = [string]$hubState.hub_id
    hub_display_name = $hubDisplayName
    hub_identity_status = [string]$hubState.hub_identity_status
    hub_state_manifest_status = [string]$hubState.hub_state_manifest_status
    hub_identity = if ($hubIdentity) { $hubIdentity.data } else { $null }
    hub_status = Resolve-HubStatus -HubOnline $hubOnline -Services $services -ComposeState $composeState
    runtime_state = $runtimeState
    compose_state = $composeState
    status_reason_code = $statusReasonCode
    hub_base_url = $hubUrl
    front_door_url = $hubUrl
    hub_address = [ordered]@{
        hostname = $env:COMPUTERNAME
        lan_ip = $lanIp
        port = Get-ImmoAppHubPort
        front_door_url = Get-ImmoAppHubBaseUrl -PreferLan
        front_door_service = "caddy"
        web_bind_host = $bindHost
        lan_enabled = ($envValues.ContainsKey("IMMOAPP_CADDY_BIND_HOST") -and [string]$envValues["IMMOAPP_CADDY_BIND_HOST"] -eq "0.0.0.0")
    }
    runtime_dependency_mode = $RuntimeDependencyMode
    agency_install_status = $AgencyInstallStatus
    internal_proof_status = [string]$runtimeDetection.internal_proof_status
    runtime_artifact_status = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "runtime_artifact_status")
    runtime_start_status = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "runtime_start_status")
    runtime_start_reason_code = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "runtime_start_reason_code")
    runtime_user_visible = [bool]$runtimeDetection.runtime_is_user_visible
    runtime_hidden_from_operator = (
        [string]$RuntimeDependencyMode -eq "managed_container_runtime" -and
        -not [bool]$runtimeDetection.runtime_is_user_visible -and
        [string]$runtimeDetection.provider_validation_status -eq "valid" -and
        [string]$runtimeDetection.agency_install_status -eq "GO"
    )
    docker_desktop_detected = (Convert-ImmoAppBoolean (Get-ImmoAppObjectValue -Data $runtimeDetection -Name "docker_desktop_detected"))
    manual_docker_desktop_internal_only = ([string]$RuntimeDependencyMode -eq "manual_docker_desktop" -or (Convert-ImmoAppBoolean (Get-ImmoAppObjectValue -Data $runtimeDetection -Name "docker_desktop_detected")))
    runtime_detection_path = $runtimeDetectionPath
    runtime_detection = $runtimeDetection
    managed_runtime_start_evidence_path = if ($managedWsl2StartEvidence) { [string](Get-ObjectValue -Data $runtimeDetection -Name "runtime_start_evidence_path") } else { "" }
    managed_runtime_start_evidence_sha256 = if ($managedWsl2StartEvidence) { Get-FileSha256 -Path ([string](Get-ObjectValue -Data $runtimeDetection -Name "runtime_start_evidence_path")) } else { "" }
    managed_runtime_start_evidence_status = if ($managedWsl2StartEvidence) { "GO" } else { "NOT_USED" }
    runtime_provider_proof = [ordered]@{
        provider_config_path = [string]$runtimeDetection.provider_config_path
        provider_config_present = [bool]$runtimeDetection.provider_config_present
        provider_config_valid = [bool]$runtimeDetection.provider_config_valid
        provider_validation_status = [string]$runtimeDetection.provider_validation_status
        provider_mode = [string](Get-ObjectValue -Data $runtimeDetection.provider -Name "provider_mode")
        proof_only = [string](Get-ObjectValue -Data $runtimeDetection.provider -Name "proof_only")
        internal_proof_status = [string]$runtimeDetection.internal_proof_status
        package_inventory_path = [string](Get-ObjectValue -Data $runtimeDetection.provider -Name "package_inventory_path")
        package_sha256 = [string](Get-ObjectValue -Data $runtimeDetection.provider -Name "package_sha256")
    }
    transport_security = "local_http_private_lan"
    docker_compose_hidden_from_user = (
        [string]$RuntimeDependencyMode -eq "managed_container_runtime" -and
        -not [bool]$runtimeDetection.runtime_is_user_visible -and
        [string]$runtimeDetection.provider_validation_status -eq "valid" -and
        [string]$runtimeDetection.agency_install_status -eq "GO"
    )
    api_health = $health
    readiness_health = $ready
    database_health = $serviceHealth.database
    storage_photos_health = $serviceHealth.storage_photos
    worker_health = $serviceHealth.worker
    backup_status = $backup
    managed_runtime_log_retention = $managedRuntimeLogRetention
    runtime_profile = $profileSummary
    data_path = $runtimePaths.AppDataRoot
    env_file_path = $envFile
    windows_firewall_rule_status = $WindowsFirewallRuleStatus
    compose_services = $services
    failing_services = $failingServices
    missing_services = $missingServices
    starting_services = $startingServices
    last_error_summary = $failureReason
}

$outputDir = Split-Path -Parent $OutputJson
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}
$evidence | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
Write-Host "Hub status evidence JSON: $OutputJson"
Write-Host "Hub status: $($evidence.hub_status)"
Write-Host "Hub URL: $hubUrl"
