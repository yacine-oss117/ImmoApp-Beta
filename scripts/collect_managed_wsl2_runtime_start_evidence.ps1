[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status", "health", "logs", "backup")]
    [string]$Action = "start",
    [string]$OutputJson = "",
    [string]$HubBaseUrl = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Join-UrlPath {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$Path
    )
    return $BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

function Invoke-FrontDoorProbe {
    param([Parameter(Mandatory = $true)][string]$BaseUrl)
    $healthStatus = 0
    $identityStatus = 0
    $frontDoorHeader = ""
    $identityKind = ""
    $identitySchema = 0
    $failure = ""
    try {
        $health = Invoke-WebRequest -Method Get -Uri (Join-UrlPath -BaseUrl $BaseUrl -Path "/api/v1/health/") -TimeoutSec 8 -UseBasicParsing
        $healthStatus = [int]$health.StatusCode
        $identity = Invoke-WebRequest -Method Get -Uri (Join-UrlPath -BaseUrl $BaseUrl -Path "/api/v1/hub/front-door/identity/") -TimeoutSec 8 -UseBasicParsing
        $identityStatus = [int]$identity.StatusCode
        $frontDoorHeader = [string]$identity.Headers["X-ImmoApp-Front-Door"]
        $identityJson = $identity.Content | ConvertFrom-Json
        $identityKind = [string](Get-ImmoAppObjectValue -Data $identityJson -Name "kind")
        $identitySchema = [int](Get-ImmoAppObjectValue -Data $identityJson -Name "schema_version")
    }
    catch {
        $failure = $_.Exception.Message
    }
    $frontDoorGo = (
        $healthStatus -eq 200 -and
        $identityStatus -eq 200 -and
        $frontDoorHeader.ToLowerInvariant() -eq "caddy" -and
        $identityKind -eq "immoapp_hub_front_door_identity" -and
        $identitySchema -eq 1
    )
    return [ordered]@{
        front_door_url = $BaseUrl
        health_status = $healthStatus
        identity_status = $identityStatus
        front_door_header = $frontDoorHeader
        identity_kind = $identityKind
        identity_schema_version = $identitySchema
        front_door_health_status = if ($frontDoorGo) { "GO" } else { "NO-GO" }
        failure_reason = $failure
    }
}

function Test-ImmoAppEndpointReachable {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $response = Invoke-WebRequest -Method Get -Uri $Url -TimeoutSec 3 -UseBasicParsing
        return [ordered]@{
            url = $Url
            reachable = $true
            status = [int]$response.StatusCode
            error = ""
        }
    }
    catch {
        return [ordered]@{
            url = $Url
            reachable = $false
            status = 0
            error = $_.Exception.Message
        }
    }
}

function Join-ImmoAppProcessArguments {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    return (($Arguments | ForEach-Object {
                $value = [string]$_
                if ($value -match '[\s"]') {
                    '"' + ($value.Replace('\', '\\').Replace('"', '\"')) + '"'
                }
                else {
                    $value
                }
            }) -join " ")
}

function Invoke-ImmoAppBoundedPowerShellBridge {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int]$TimeoutSeconds = 720
    )
    $stdout = [System.IO.Path]::GetTempFileName()
    $stderr = [System.IO.Path]::GetTempFileName()
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = $null
    $timedOut = $false
    $exitCode = 998
    try {
        $process = Start-Process `
            -FilePath "powershell" `
            -ArgumentList (Join-ImmoAppProcessArguments -Arguments $Arguments) `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -PassThru `
            -WindowStyle Hidden
        if (-not $process.WaitForExit([Math]::Max(1, $TimeoutSeconds) * 1000)) {
            $timedOut = $true
            try {
                & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
            }
            catch {
                try { $process.Kill() } catch { }
            }
            $exitCode = 124
        }
        else {
            $exitCode = [int]$process.ExitCode
        }
    }
    catch {
        $exitCode = 998
        Set-Content -LiteralPath $stderr -Value ([string]$_.Exception.Message) -Encoding UTF8
    }
    finally {
        $stopwatch.Stop()
    }
    $output = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw -ErrorAction SilentlyContinue } else { "" }
    $errorText = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue } else { "" }
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    return [ordered]@{
        exit_code = $exitCode
        timed_out = $timedOut
        timeout_seconds = [int]$TimeoutSeconds
        elapsed_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        output = (($output + $errorText) | Out-String).Trim()
    }
}

$paths = Ensure-ImmoAppRuntimeLayout
if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $paths.LogsRoot "managed_wsl2_runtime_start_evidence.json"
}

$startRunId = [guid]::NewGuid().ToString("N").ToLowerInvariant()
$runtimeBridgeTimeoutSeconds = 720
$timeoutOverride = [Environment]::GetEnvironmentVariable("IMMOAPP_MANAGED_WSL2_BRIDGE_TIMEOUT_SECONDS")
if (-not [string]::IsNullOrWhiteSpace($timeoutOverride)) {
    $parsedTimeout = 0
    if ([int]::TryParse($timeoutOverride, [ref]$parsedTimeout) -and $parsedTimeout -gt 0) {
        $runtimeBridgeTimeoutSeconds = $parsedTimeout
    }
}
$identityBridgeTimeoutSeconds = 120
$identityTimeoutOverride = [Environment]::GetEnvironmentVariable("IMMOAPP_MANAGED_WSL2_IDENTITY_TIMEOUT_SECONDS")
if (-not [string]::IsNullOrWhiteSpace($identityTimeoutOverride)) {
    $parsedIdentityTimeout = 0
    if ([int]::TryParse($identityTimeoutOverride, [ref]$parsedIdentityTimeout) -and $parsedIdentityTimeout -gt 0) {
        $identityBridgeTimeoutSeconds = $parsedIdentityTimeout
    }
}
$detectionPath = Join-Path $paths.LogsRoot "hub_runtime_detection_for_managed_wsl2_start.json"
$detection = Invoke-ImmoAppHubRuntimeDetection -OutputJson $detectionPath
$provider = Get-ImmoAppObjectValue -Data $detection -Name "provider"
$providerConfigPath = [string](Get-ImmoAppObjectValue -Data $detection -Name "provider_config_path")
$providerConfigSha = if ($providerConfigPath -and (Test-Path -LiteralPath $providerConfigPath -PathType Leaf)) { Get-ImmoAppFileSha256 -Path $providerConfigPath } else { "" }
$artifactInventoryPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "runtime_artifact_inventory_path")
$artifactInventorySha = [string](Get-ImmoAppObjectValue -Data $provider -Name "runtime_artifact_inventory_sha256")
$runtimeCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "managed_runtime_command_path")
$statusCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "managed_status_command_path")
$healthCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "managed_health_command_path")
$logsCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "managed_logs_command_path")
$backupCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "managed_backup_command_path")
$stopCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "managed_stop_command_path")
$restartCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "managed_restart_command_path")
if ([string]::IsNullOrWhiteSpace($runtimeCommandPath)) {
    $runtimeCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "runtime_executable_path")
}
if ([string]::IsNullOrWhiteSpace($statusCommandPath)) {
    $statusCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "compose_executable_path")
}
$commandPath = switch ($Action) {
    "stop" { if ($stopCommandPath) { $stopCommandPath } else { $runtimeCommandPath } }
    "restart" { if ($restartCommandPath) { $restartCommandPath } else { $runtimeCommandPath } }
    "status" { $statusCommandPath }
    "health" { if ($healthCommandPath) { $healthCommandPath } else { $statusCommandPath } }
    "logs" { if ($logsCommandPath) { $logsCommandPath } else { $runtimeCommandPath } }
    "backup" { if ($backupCommandPath) { $backupCommandPath } else { $runtimeCommandPath } }
    default { $runtimeCommandPath }
}
$commandSha = if ($commandPath -and (Test-Path -LiteralPath $commandPath -PathType Leaf)) { Get-ImmoAppFileSha256 -Path $commandPath } else { "" }
$bootstrapEvidencePath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_bootstrap_evidence.json"
$bootstrapBridge = Invoke-ImmoAppBoundedPowerShellBridge `
    -Arguments @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $PSScriptRoot "bootstrap_managed_wsl2_runtime.ps1"),
        "-OutputJson",
        $bootstrapEvidencePath
    ) `
    -TimeoutSeconds $identityBridgeTimeoutSeconds
$bootstrapText = [string]$bootstrapBridge.output
$bootstrapExitCode = [int]$bootstrapBridge.exit_code
$bootstrapBridgeTimedOut = [bool]$bootstrapBridge.timed_out
$bootstrapBridgeElapsedSeconds = [double]$bootstrapBridge.elapsed_seconds
$bootstrapEvidence = if (Test-Path -LiteralPath $bootstrapEvidencePath -PathType Leaf) { Get-Content -LiteralPath $bootstrapEvidencePath -Raw | ConvertFrom-Json } else { $null }
$bootstrapEvidenceSha = if (Test-Path -LiteralPath $bootstrapEvidencePath -PathType Leaf) { Get-ImmoAppFileSha256 -Path $bootstrapEvidencePath } else { "" }
$expectedDistroName = [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "expected_distro_name")
$actualDistroName = [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "actual_distro_name")
$runtimeIdentityStatus = [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "runtime_identity_status")
$containerEngineStatus = [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "container_engine_status")
$composeStatus = [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "compose_status")
$bootstrapComposeCliStatus = [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "compose_cli_status")
$serviceStatus = [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "service_status")
$services = @(Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "services")
$preStartFrontDoorUrl = (Get-ImmoAppHubBaseUrl -PreferLan).TrimEnd("/") + "/api/v1/health/"
$preStartBackendDirectUrl = "http://127.0.0.1:18000/api/v1/health/"
if ([Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1") {
    $testFrontDoorPrecheckUrl = [Environment]::GetEnvironmentVariable("IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL")
    $testBackendPrecheckUrl = [Environment]::GetEnvironmentVariable("IMMOAPP_TEST_PRESTART_BACKEND_URL")
    if (-not [string]::IsNullOrWhiteSpace($testFrontDoorPrecheckUrl)) { $preStartFrontDoorUrl = $testFrontDoorPrecheckUrl }
    if (-not [string]::IsNullOrWhiteSpace($testBackendPrecheckUrl)) { $preStartBackendDirectUrl = $testBackendPrecheckUrl }
}
$preStartFrontDoor = if ($Action -eq "start") { Test-ImmoAppEndpointReachable -Url $preStartFrontDoorUrl } else { [ordered]@{ url = ""; reachable = $false; status = 0; error = ""; skipped = $true } }
$preStartBackendDirect = if ($Action -eq "start") { Test-ImmoAppEndpointReachable -Url $preStartBackendDirectUrl } else { [ordered]@{ url = ""; reachable = $false; status = 0; error = ""; skipped = $true } }
$preStartContaminated = ($Action -eq "start" -and ([bool]$preStartFrontDoor.reachable -or [bool]$preStartBackendDirect.reachable))

$wrapperExitCode = 999
$wrapperOutput = ""
$wrapperError = ""
$runtimeBridgeTimedOut = $false
$runtimeBridgeElapsedSeconds = 0.0
$runtimeCommandStatus = "NO-GO"
$reasonCode = "managed_wsl2_runtime_provider_invalid"
$servicePayload = $null
$distroIdentityStatus = "NO-GO"
$dockerDaemonStatus = "NO-GO"
$dockerInfoStatus = "NO-GO"
$composeCliStatus = if ([string]::IsNullOrWhiteSpace($bootstrapComposeCliStatus)) { "NO-GO" } else { $bootstrapComposeCliStatus }
$imageArchiveStatus = "NO-GO"
$imageInventoryStatus = "NO-GO"
$imageLoadStatus = "not_attempted"
$imagePresenceStatus = "NO-GO"
$composePayloadStatus = "NO-GO"
$composePullPolicyStatus = "NO-GO"
$composeUpStatus = "NO-GO"
$composeServiceStatus = "NO-GO"
$frontDoorPartialStatus = "NO-GO"
$imageArchivePath = ""
$imageArchiveSha256 = ""
$imageBundleInventoryPath = ""
$imageBundleInventorySha256 = ""
$runtimeComposeFile = ""
$runtimeComposeProject = ""
$runtimeFailingServices = @()
$dockerStartAttempted = $false
$dockerStartTimeoutSeconds = 0
$dockerStartElapsedSeconds = 0
$dockerStartExitCode = ""
$dockerStartDiagnostics = ""
$serviceReadinessTimeoutSeconds = 0
$serviceReadinessElapsedSeconds = 0
$imageArchiveHostPath = ""
$imageArchiveWslPath = ""
$imageBundleInventoryHostPath = ""
$imageBundleInventoryWslPath = ""
$caddyBindHost = ""
$caddyBindMode = ""

if ($preStartContaminated) {
    $wrapperError = "Pre-start front-door/backend endpoint was already reachable; managed runtime proof is contaminated."
    $reasonCode = "managed_wsl2_pre_start_port_contamination"
}
elseif ($bootstrapBridgeTimedOut) {
    $wrapperError = "Managed WSL2 runtime bootstrap command timed out. $($bootstrapText | Out-String)"
    $reasonCode = "managed_wsl2_runtime_bridge_timeout"
}
elseif ($bootstrapExitCode -ne 0 -or [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "proof_result") -ne "GO") {
    $wrapperError = "Managed WSL2 runtime bootstrap did not reach GO. $($bootstrapText | Out-String)"
    $reasonCode = [string](Get-ImmoAppObjectValue -Data $bootstrapEvidence -Name "reason_code")
    if ([string]::IsNullOrWhiteSpace($reasonCode)) { $reasonCode = "managed_wsl2_runtime_bootstrap_not_go" }
}
elseif ([string](Get-ImmoAppObjectValue -Data $detection -Name "runtime_dependency_mode") -ne "managed_wsl2_container_runtime_artifact") {
    $wrapperError = "Active runtime is not managed_wsl2_container_runtime_artifact."
    $reasonCode = "managed_wsl2_runtime_artifact_provider_missing"
}
elseif ([string](Get-ImmoAppObjectValue -Data $detection -Name "provider_validation_status") -ne "valid") {
    $wrapperError = "Managed WSL2 artifact provider is invalid."
    $reasonCode = [string](Get-ImmoAppObjectValue -Data $detection -Name "reason_code")
}
elseif ([string]::IsNullOrWhiteSpace($commandPath) -or -not (Test-Path -LiteralPath $commandPath -PathType Leaf)) {
    $wrapperError = "Managed WSL2 runtime artifact command is missing."
    $reasonCode = "managed_wsl2_runtime_wrapper_missing"
}
else {
    $invokeAction = switch ($Action) {
        "start" { "start" }
        "restart" { "restart" }
        "stop" { "stop" }
        "logs" { "logs" }
        "backup" { "backup" }
        default { "status" }
    }
    $command = Invoke-ImmoAppBoundedPowerShellBridge `
        -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $commandPath,
            $invokeAction
        ) `
        -TimeoutSeconds $runtimeBridgeTimeoutSeconds
    $wrapperExitCode = [int]$command.exit_code
    $runtimeBridgeTimedOut = [bool]$command.timed_out
    $runtimeBridgeElapsedSeconds = [double]$command.elapsed_seconds
    $wrapperOutput = [string]$command.output
    if ($runtimeBridgeTimedOut) {
        $runtimeCommandStatus = "NO-GO"
        $wrapperError = $wrapperOutput
        $reasonCode = "managed_wsl2_runtime_bridge_timeout"
    }
    elseif ($wrapperExitCode -eq 0) {
        $runtimeCommandStatus = "GO"
        $reasonCode = "managed_wsl2_runtime_command_ok"
        try {
            $servicePayload = $wrapperOutput | ConvertFrom-Json
            $serviceStatusFromOutput = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "service_status")
            if (-not [string]::IsNullOrWhiteSpace($serviceStatusFromOutput)) {
                $serviceStatus = $serviceStatusFromOutput
            }
            $serviceListFromOutput = @(Get-ImmoAppObjectValue -Data $servicePayload -Name "services")
            if ($serviceListFromOutput.Count -gt 0) {
                $services = @($serviceListFromOutput)
            }
            $runtimeFailingServices = @(Get-ImmoAppObjectValue -Data $servicePayload -Name "failing_services")
            $distroIdentityStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "distro_identity_status")
            $dockerDaemonStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "docker_daemon_status")
            $dockerInfoStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "docker_info_status")
            $composeCliStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "compose_cli_status")
            $imageArchiveStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_archive_status")
            $imageInventoryStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_inventory_status")
            $imageLoadStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_load_status")
            $imagePresenceStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_presence_status")
            $composePayloadStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "compose_payload_status")
            $composePullPolicyStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "compose_pull_policy_status")
            $composeUpStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "compose_up_status")
            $composeServiceStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "compose_service_status")
            $frontDoorPartialStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "front_door_partial_status")
            $imageArchivePath = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_archive_path")
            $imageArchiveHostPath = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_archive_host_path")
            $imageArchiveWslPath = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_archive_wsl_path")
            $imageArchiveSha256 = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_archive_sha256")
            $imageBundleInventoryPath = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_bundle_inventory_path")
            $imageBundleInventoryHostPath = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_bundle_inventory_host_path")
            $imageBundleInventoryWslPath = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_bundle_inventory_wsl_path")
            $imageBundleInventorySha256 = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "image_bundle_inventory_sha256")
            $runtimeComposeFile = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "compose_file")
            $runtimeComposeProject = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "compose_project")
            $dockerStartAttempted = [bool](Get-ImmoAppObjectValue -Data $servicePayload -Name "docker_start_attempted")
            $dockerStartTimeoutSeconds = [int](Get-ImmoAppObjectValue -Data $servicePayload -Name "docker_start_timeout_seconds")
            $dockerStartElapsedSeconds = [int](Get-ImmoAppObjectValue -Data $servicePayload -Name "docker_start_elapsed_seconds")
            $dockerStartExitCode = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "docker_start_exit_code")
            $dockerStartDiagnostics = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "docker_start_diagnostics")
            $serviceReadinessTimeoutSeconds = [int](Get-ImmoAppObjectValue -Data $servicePayload -Name "service_readiness_timeout_seconds")
            $serviceReadinessElapsedSeconds = [int](Get-ImmoAppObjectValue -Data $servicePayload -Name "service_readiness_elapsed_seconds")
            $caddyBindHost = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "caddy_bind_host")
            $caddyBindMode = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "caddy_bind_mode")
        }
        catch {
            if ($Action -in @("start", "restart", "status", "health")) {
                $runtimeCommandStatus = "NO-GO"
                $reasonCode = "managed_wsl2_runtime_service_status_missing"
                $wrapperError = "Managed WSL2 runtime command did not emit JSON service status."
            }
        }
        if ($Action -in @("start", "restart", "status", "health")) {
            if ($runtimeCommandStatus -eq "GO" -and $serviceStatus -ne "GO") {
                $runtimeCommandStatus = "NO-GO"
                $payloadReason = if ($servicePayload) { [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "reason_code") } else { "" }
                $reasonCode = if ([string]::IsNullOrWhiteSpace($payloadReason)) { "managed_wsl2_runtime_service_status_not_go" } else { $payloadReason }
                $wrapperError = "Managed WSL2 runtime service status is not GO."
            }
            $requiredRuntimeGoFields = @(
                @{ name = "distro_identity_status"; value = $distroIdentityStatus },
                @{ name = "docker_daemon_status"; value = $dockerDaemonStatus },
                @{ name = "docker_info_status"; value = $dockerInfoStatus },
                @{ name = "compose_up_status"; value = $composeUpStatus },
                @{ name = "compose_service_status"; value = $composeServiceStatus }
            )
            if ($Action -in @("start", "restart", "status")) {
                $requiredRuntimeGoFields += @(
                    @{ name = "image_archive_status"; value = $imageArchiveStatus },
                    @{ name = "image_inventory_status"; value = $imageInventoryStatus },
                    @{ name = "image_presence_status"; value = $imagePresenceStatus },
                    @{ name = "compose_payload_status"; value = $composePayloadStatus },
                    @{ name = "compose_pull_policy_status"; value = $composePullPolicyStatus }
                )
            }
            foreach ($requiredRuntimeGoField in $requiredRuntimeGoFields) {
                if ($runtimeCommandStatus -eq "GO" -and [string]$requiredRuntimeGoField.value -ne "GO") {
                    $runtimeCommandStatus = "NO-GO"
                    $payloadReason = if ($servicePayload) { [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "reason_code") } else { "" }
                    $reasonCode = if ([string]::IsNullOrWhiteSpace($payloadReason)) { "managed_wsl2_runtime_required_step_not_go" } else { $payloadReason }
                    $wrapperError = "Managed WSL2 runtime required step is not GO: $($requiredRuntimeGoField.name)=$($requiredRuntimeGoField.value)"
                }
            }
        }
        if ($Action -eq "backup") {
            $backupStatus = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "backup_status")
            if ($runtimeCommandStatus -eq "GO" -and $backupStatus -ne "GO") {
                $runtimeCommandStatus = "NO-GO"
                $reasonCode = [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "reason_code")
                if ([string]::IsNullOrWhiteSpace($reasonCode)) { $reasonCode = "managed_wsl2_backup_not_go" }
                $wrapperError = "Managed WSL2 runtime backup status is not GO."
            }
        }
    }
    else {
        $runtimeCommandStatus = "NO-GO"
        $wrapperError = $wrapperOutput
        if ($wrapperOutput -match "(managed_wsl2_[a-z0-9_]+|wsl2_unavailable)") {
            $reasonCode = $Matches[1]
        }
        else {
            $reasonCode = "managed_wsl2_runtime_command_failed"
        }
    }
}

$frontDoorProofRequired = ($Action -in @("start", "restart", "status", "health"))
$explicitFrontDoorUrl = -not [string]::IsNullOrWhiteSpace($HubBaseUrl)
$frontDoorUrl = if (-not $frontDoorProofRequired) {
    ""
} elseif ($explicitFrontDoorUrl) {
    $HubBaseUrl.TrimEnd("/")
} else {
    "http://127.0.0.1:$(Get-ImmoAppHubPort)"
}
$frontDoorHost = ""
$frontDoorIsLoopback = $true
try {
    $frontDoorHost = ([Uri]$frontDoorUrl).Host
    $frontDoorIsLoopback = (
        $frontDoorHost -eq "localhost" -or
        $frontDoorHost -eq "127.0.0.1" -or
        $frontDoorHost -eq "::1"
    )
}
catch {
    $frontDoorIsLoopback = $false
}
$wslPortProxy = [ordered]@{
    status = "not_required"
    applied = $false
    verified = $true
    listen_address = $frontDoorHost
    listen_port = [int](Get-ImmoAppHubPort)
    connect_address = ""
    connect_port = [int](Get-ImmoAppHubPort)
    rule_scope = "wsl_portproxy"
    reason_code = "front_door_url_is_loopback"
}
if ($explicitFrontDoorUrl -and (-not $frontDoorIsLoopback) -and $caddyBindMode -ne "local") {
    $wslPortProxy = Ensure-ImmoAppHubWslPortProxy `
        -LanAccess `
        -Requested `
        -DistroName $expectedDistroName `
        -ListenAddress $frontDoorHost `
        -Port ([int](Get-ImmoAppHubPort))
}
$wslPortProxyStatus = [string](Get-ImmoAppObjectValue -Data $wslPortProxy -Name "status")
$wslPortProxyVerified = Convert-ImmoAppBoolean (Get-ImmoAppObjectValue -Data $wslPortProxy -Name "verified")
$frontDoor = if ($frontDoorProofRequired) {
    Invoke-FrontDoorProbe -BaseUrl $frontDoorUrl
}
else {
    [ordered]@{
        front_door_url = $frontDoorUrl
        health_status = 0
        identity_status = 0
        front_door_header = ""
        identity_kind = ""
        identity_schema_version = 0
        front_door_health_status = "not_required"
        failure_reason = ""
    }
}
$caddyLanBindStatus = if (-not $frontDoorProofRequired) { "not_required" } elseif ((-not $explicitFrontDoorUrl) -or $frontDoorIsLoopback) { "not_required" } elseif ($caddyBindMode -eq "local") { "NO-GO" } else { "GO" }
$identityOk = ($runtimeIdentityStatus -eq "GO" -and $containerEngineStatus -eq "GO" -and $composeStatus -eq "GO")
$serviceProofRequired = ($Action -in @("start", "restart", "status", "health", "backup"))
$serviceOk = ((-not $serviceProofRequired) -or $serviceStatus -eq "GO")
$networkBridgeOk = ((-not $frontDoorProofRequired) -or (-not $explicitFrontDoorUrl) -or $frontDoorIsLoopback -or ($wslPortProxyVerified -and $wslPortProxyStatus -in @("created", "updated", "already_present_valid")))
$frontDoorOk = ((-not $frontDoorProofRequired) -or [string]$frontDoor.front_door_health_status -eq "GO")
$proofResult = if ($identityOk -and $runtimeCommandStatus -eq "GO" -and $serviceOk -and $networkBridgeOk -and $frontDoorOk -and $caddyLanBindStatus -ne "NO-GO") { "GO" } else { "NO-GO" }
if ($proofResult -ne "GO" -and -not $networkBridgeOk -and $reasonCode -eq "managed_wsl2_runtime_command_ok") {
    $reasonCode = if ([string]::IsNullOrWhiteSpace([string](Get-ImmoAppObjectValue -Data $wslPortProxy -Name "reason_code"))) {
        "managed_wsl2_portproxy_not_verified"
    } else {
        [string](Get-ImmoAppObjectValue -Data $wslPortProxy -Name "reason_code")
    }
}
if ($proofResult -ne "GO" -and $frontDoorProofRequired -and [string]$frontDoor.front_door_health_status -ne "GO" -and $reasonCode -eq "managed_wsl2_runtime_command_ok") {
    $reasonCode = "managed_wsl2_front_door_health_not_go"
}
if ($proofResult -ne "GO" -and $caddyLanBindStatus -eq "NO-GO" -and $reasonCode -eq "managed_wsl2_runtime_command_ok") {
    $reasonCode = "managed_wsl2_caddy_lan_bind_not_proven"
}

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_start_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    start_run_id = $startRunId
    action = $Action
    runtime_dependency_mode = "managed_wsl2_container_runtime_artifact"
    provider_config_path = $providerConfigPath
    provider_config_sha256 = $providerConfigSha
    runtime_artifact_inventory_path = $artifactInventoryPath
    runtime_artifact_inventory_sha256 = $artifactInventorySha
    managed_runtime_command_path = $commandPath
    managed_runtime_command_sha256 = $commandSha
    managed_status_command_path = $statusCommandPath
    managed_health_command_path = $healthCommandPath
    managed_logs_command_path = $logsCommandPath
    managed_backup_command_path = $backupCommandPath
    managed_stop_command_path = $stopCommandPath
    managed_restart_command_path = $restartCommandPath
    expected_distro_name = $expectedDistroName
    actual_distro_name = $actualDistroName
    runtime_identity_status = $runtimeIdentityStatus
    container_engine_status = $containerEngineStatus
    compose_status = $composeStatus
    bootstrap_evidence_path = $bootstrapEvidencePath
    bootstrap_evidence_sha256 = $bootstrapEvidenceSha
    bootstrap_exit_code = $bootstrapExitCode
    bootstrap_bridge_timeout_seconds = $identityBridgeTimeoutSeconds
    bootstrap_bridge_timed_out = $bootstrapBridgeTimedOut
    bootstrap_bridge_elapsed_seconds = $bootstrapBridgeElapsedSeconds
    pre_start_front_door_reachable = [bool]$preStartFrontDoor.reachable
    pre_start_backend_direct_reachable = [bool]$preStartBackendDirect.reachable
    pre_start_front_door_probe = $preStartFrontDoor
    pre_start_backend_direct_probe = $preStartBackendDirect
    runtime_detection_path = $detectionPath
    runtime_detection = $detection
    wrapper_exit_code = $wrapperExitCode
    wrapper_output = $wrapperOutput
    wrapper_error = $wrapperError
    runtime_bridge_timeout_seconds = $runtimeBridgeTimeoutSeconds
    runtime_bridge_elapsed_seconds = $runtimeBridgeElapsedSeconds
    runtime_bridge_timed_out = $runtimeBridgeTimedOut
    runtime_command_status = $runtimeCommandStatus
    compose_service_status = if ($runtimeCommandStatus -eq "GO" -and $serviceStatus -eq "GO") { "GO" } else { "NO-GO" }
    service_status = $serviceStatus
    distro_identity_status = $distroIdentityStatus
    docker_daemon_status = $dockerDaemonStatus
    docker_info_status = $dockerInfoStatus
    compose_cli_status = $composeCliStatus
    image_archive_status = $imageArchiveStatus
    image_inventory_status = $imageInventoryStatus
    image_load_status = $imageLoadStatus
    image_presence_status = $imagePresenceStatus
    compose_payload_status = $composePayloadStatus
    compose_pull_policy_status = $composePullPolicyStatus
    compose_up_status = $composeUpStatus
    runtime_compose_service_status = $composeServiceStatus
    front_door_partial_status = $frontDoorPartialStatus
    image_archive_path = $imageArchivePath
    image_archive_host_path = $imageArchiveHostPath
    image_archive_wsl_path = $imageArchiveWslPath
    image_archive_sha256 = $imageArchiveSha256
    image_bundle_inventory_path = $imageBundleInventoryPath
    image_bundle_inventory_host_path = $imageBundleInventoryHostPath
    image_bundle_inventory_wsl_path = $imageBundleInventoryWslPath
    image_bundle_inventory_sha256 = $imageBundleInventorySha256
    runtime_compose_file = $runtimeComposeFile
    runtime_compose_project = $runtimeComposeProject
    docker_start_attempted = $dockerStartAttempted
    docker_start_timeout_seconds = $dockerStartTimeoutSeconds
    docker_start_elapsed_seconds = $dockerStartElapsedSeconds
    docker_start_exit_code = $dockerStartExitCode
    docker_start_diagnostics = $dockerStartDiagnostics
    service_readiness_timeout_seconds = $serviceReadinessTimeoutSeconds
    service_readiness_elapsed_seconds = $serviceReadinessElapsedSeconds
    caddy_bind_host = $caddyBindHost
    caddy_bind_mode = $caddyBindMode
    service_proof_required = [bool]$serviceProofRequired
    explicit_front_door_url_requested = [bool]$explicitFrontDoorUrl
    caddy_lan_bind_status = $caddyLanBindStatus
    wsl_portproxy_status = $wslPortProxyStatus
    wsl_portproxy_verified = [bool]$wslPortProxyVerified
    wsl_portproxy = $wslPortProxy
    service_statuses = [ordered]@{
        managed_wsl2_bridge = $runtimeCommandStatus
        runtime_identity = $runtimeIdentityStatus
        container_engine = $containerEngineStatus
        docker_daemon = $dockerDaemonStatus
        docker_info = $dockerInfoStatus
        compose_cli = $composeCliStatus
        compose = $composeStatus
        image_archive = $imageArchiveStatus
        image_inventory = $imageInventoryStatus
        images = $imagePresenceStatus
        compose_payload = $composePayloadStatus
        compose_pull_policy = $composePullPolicyStatus
        compose_up = $composeUpStatus
        services = $serviceStatus
        wsl_portproxy = if ($networkBridgeOk) { "GO" } else { "NO-GO" }
        caddy_front_door = [string]$frontDoor.front_door_health_status
    }
    services = @($services)
    failing_services = @($runtimeFailingServices)
    front_door_url = [string]$frontDoor.front_door_url
    front_door_health_status = [string]$frontDoor.front_door_health_status
    health_status = [int]$frontDoor.health_status
    identity_status = [int]$frontDoor.identity_status
    front_door_header = [string]$frontDoor.front_door_header
    identity_kind = [string]$frontDoor.identity_kind
    identity_schema_version = [int]$frontDoor.identity_schema_version
    front_door_failure_reason = [string]$frontDoor.failure_reason
    network_boundary_status = "not_collected"
    backup_status = if ($Action -eq "backup") { [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "backup_status") } else { "not_requested" }
    backup_bundle_path = if ($Action -eq "backup") { [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "backup_bundle_path") } else { "" }
    backup_bundle_wsl_path = if ($Action -eq "backup") { [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "backup_bundle_wsl_path") } else { "" }
    backup_bundle_sha256 = if ($Action -eq "backup") { [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "backup_bundle_sha256") } else { "" }
    backup_bundle_bytes = if ($Action -eq "backup") { [int64](Get-ImmoAppObjectValue -Data $servicePayload -Name "backup_bundle_bytes") } else { 0 }
    database_dump_sha256 = if ($Action -eq "backup") { [string](Get-ImmoAppObjectValue -Data $servicePayload -Name "database_dump_sha256") } else { "" }
    storage_object_count = if ($Action -eq "backup") { [int](Get-ImmoAppObjectValue -Data $servicePayload -Name "storage_object_count") } else { 0 }
    agency_install_status = "NO_GO"
    public_beta_status = "NO_GO"
    proof_result = $proofResult
    reason_code = $reasonCode
}

$write = Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 14
$payload["evidence_path"] = [string]$OutputJson
$payload["evidence_sha256"] = [string]$write.sha256
$payload | ConvertTo-Json -Depth 14
if ($proofResult -ne "GO") { exit 1 }
