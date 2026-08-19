param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "status", "health", "logs", "support", "backup-now", "open-desktop", "copy-url", "rename-hub", "finish-hub-setup", "identity", "front-door", "runtime-status", "install-runtime-candidate", "install-runtime-artifact", "remove-runtime-candidate", "cleanup-runtime-logs", "delete-hub-data", "firewall-status", "connection-details")]
    [string]$Action,
    [string]$HubBaseUrl = "",
    [string]$HubDisplayName = "",
    [string]$OutputJson = "",
    [double]$MachineTotalMemoryGb = 0,
    [int]$MachineLogicalProcessors = 0,
    [int]$RetentionDays = 14,
    [Int64]$MaxTotalBytes = 536870912,
    [string]$RuntimeProfileJson = "",
    [switch]$AllowMergeExistingWslConfig,
    [switch]$ConfirmInstallRuntimeCandidate,
    [switch]$ConfirmInstallRuntimeArtifact,
    [switch]$ConfirmDeleteHubData,
    [string]$TypedConfirmation = "",
    [string]$OwnerAuthorizationEvidenceJson = "",
    [switch]$UseWindowsVolumes,
    [switch]$NoWindowsVolumes
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")
. (Join-Path $PSScriptRoot "hub_manager_authorization.ps1")

function Invoke-StackAction {
    param(
        [Parameter(Mandatory = $true)][string]$StackAction,
        [string]$Path = ""
    )
    $runtimeDetection = Resolve-ImmoAppHubRuntimeDetection
    if (
        [bool](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "provider_config_present") -and
        -not [bool](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "provider_config_valid")
    ) {
        throw "managed_runtime_provider_invalid|Hub runtime provider config is present but invalid; Hub Manager will not fall back to repo/dev or manual Docker."
    }
    if ([string]$runtimeDetection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_candidate") {
        throw "managed_wsl2_runtime_artifact_missing|Managed WSL2 runtime candidate provider is registered, but no real ImmoApp-managed container runtime artifact is installed. Install the runtime artifact before Hub Manager can start the Hub through this path."
    }
    if ([string]$runtimeDetection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact") {
        $managedAction = switch ($StackAction) {
            "up" { "start" }
            "down" { "stop" }
            "restart-app" { "restart" }
            "logs" { "logs" }
            default { "status" }
        }
        Invoke-ManagedWsl2RuntimeArtifactAction -ManagedAction $managedAction -Path $Path | Out-Null
        return
    }
    $scriptSource = Get-ImmoAppCurrentScriptRootSource
    if ($scriptSource -in @("installed_app", "installed_programdata")) {
        throw "managed_runtime_provider_missing|Installed Hub Manager requires an ImmoApp-managed runtime provider. It will not start the developer Docker stack from an installed package."
    }
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "stack.ps1"), "-Action", $StackAction)
    if ($UseWindowsVolumes) { $args += "-UseWindowsVolumes" }
    if ($NoWindowsVolumes) { $args += "-NoWindowsVolumes" }
    & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "Hub $Action failed while running stack action '$StackAction'."
    }
}

function Invoke-ManagedWsl2RuntimeArtifactAction {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("start", "stop", "restart", "status", "health", "logs", "backup")]
        [string]$ManagedAction,
        [string]$Path = ""
    )
    $paths = Ensure-ImmoAppRuntimeLayout
    if ([string]::IsNullOrWhiteSpace($Path)) {
        $fileName = if ($ManagedAction -in @("start", "restart")) {
            "managed_wsl2_runtime_start_evidence.json"
        } else {
            "managed_wsl2_runtime_${ManagedAction}_evidence.json"
        }
        $Path = Join-Path $paths.LogsRoot $fileName
    }
    $args = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "collect_managed_wsl2_runtime_start_evidence.ps1"),
        "-Action", $ManagedAction,
        "-OutputJson", $Path
    )
    # Managed runtime start/status/health prove the local installed Hub.
    # LAN reachability is collected separately so a broken portproxy/firewall
    # cannot make local Hub startup look failed.
    $effectiveHubBaseUrl = $HubBaseUrl
    if (-not [string]::IsNullOrWhiteSpace($effectiveHubBaseUrl)) {
        $args += @("-HubBaseUrl", $effectiveHubBaseUrl)
    }
    $text = & powershell @args
    $exitCode = $LASTEXITCODE
    $payload = $null
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    if ($exitCode -ne 0) {
        $reason = if ($payload) { [string]$payload.reason_code } else { (($text | Out-String).Trim()) }
        throw "$reason|Managed WSL2 runtime artifact action '$ManagedAction' did not reach GO. Evidence: $Path"
    }
    return $payload
}

function Resolve-DesktopExePath {
    return (Resolve-ImmoAppDesktopExecutable).path
}

function Get-HubDisplayNameForManager {
    try {
        $identity = Read-ImmoAppHubIdentity -Optional
        if ($identity) { return [string]$identity.hub_display_name }
    }
    catch {
        return ""
    }
    return ""
}

function Write-ManagerJson {
    param(
        [Parameter(Mandatory = $true)]$Payload,
        [string]$Path = ""
    )
    if ($Path) {
        $paths = Ensure-ImmoAppRuntimeLayout
        Write-ImmoAppSafeJson -Path $Path -Payload $Payload -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 8
}

function Add-HubManagerLocalStateToPayload {
    param([Parameter(Mandatory = $true)]$Payload)

    $state = Get-ImmoAppHubStateSummary
    $values = [ordered]@{
        hub_id = [string]$state.hub_id
        hub_display_name = [string]$state.hub_display_name
        hub_identity_status = [string]$state.hub_identity_status
        hub_identity_path = [string]$state.hub_identity_path
        hub_state_manifest_status = [string]$state.hub_state_manifest_status
        hub_state_manifest_path = [string]$state.hub_state_manifest_path
    }
    foreach ($entry in $values.GetEnumerator()) {
        $Payload | Add-Member `
            -MemberType NoteProperty `
            -Name ([string]$entry.Key) `
            -Value $entry.Value `
            -Force
    }
    return $Payload
}

function Test-HubManagerGenericOwnerAuthorizationRequired {
    param([Parameter(Mandatory = $true)][string]$ManagerAction)

    return $ManagerAction -in @(
        "finish-hub-setup",
        "rename-hub",
        "install-runtime-candidate",
        "install-runtime-artifact",
        "remove-runtime-candidate",
        "cleanup-runtime-logs",
        "backup-now",
        "logs"
    )
}

function Convert-HubManagerActionToOwnerAuthorizationAction {
    param([Parameter(Mandatory = $true)][string]$ManagerAction)

    if ($ManagerAction -eq "delete-hub-data") { return "delete_hub_data" }
    return $ManagerAction
}

function Get-HubManagerOwnerAuthorizationScope {
    param([Parameter(Mandatory = $true)][string]$OwnerAuthorizationAction)

    if ($OwnerAuthorizationAction -eq "delete_hub_data") { return "hub_data_delete" }
    return "hub_manager_protected_action"
}

function New-HubManagerOwnerAuthorizationFailurePayload {
    param(
        [Parameter(Mandatory = $true)][string]$ManagerAction,
        [Parameter(Mandatory = $true)][string]$ReasonCode,
        [string]$EvidencePath = ""
    )

    return [ordered]@{
        kind = "immoapp_hub_manager_owner_authorization"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        action = [string]$ManagerAction
        source = "hub_db"
        owner_authorization_status = "NO-GO"
        proof_result = "NO-GO"
        protected_action_blocked = $true
        reason_code = [string]$ReasonCode
        owner_authorization_evidence_path = [string]$EvidencePath
        agency_install_status = "NO_GO"
        public_beta_status = "NO_GO"
    }
}

function Assert-HubManagerGenericOwnerAuthorization {
    param(
        [Parameter(Mandatory = $true)][string]$ManagerAction,
        [string]$EvidencePath = "",
        [string]$Path = "",
        [string]$HubBaseUrl = ""
    )

    if (-not (Test-HubManagerGenericOwnerAuthorizationRequired -ManagerAction $ManagerAction)) {
        return
    }

    $ownerAction = Convert-HubManagerActionToOwnerAuthorizationAction -ManagerAction $ManagerAction
    $scope = Get-HubManagerOwnerAuthorizationScope -OwnerAuthorizationAction $ownerAction
    try {
        Read-ImmoAppHubOwnerAuthorizationEvidence `
            -Path $EvidencePath `
            -ExpectedAction $ownerAction `
            -ExpectedScope $scope `
            -HubBaseUrl $HubBaseUrl | Out-Null
    }
    catch {
        $reason = ($_.Exception.Message -split "\|")[0]
        if ([string]::IsNullOrWhiteSpace($reason)) { $reason = "hub_manager_owner_authorization_failed" }
        $payload = New-HubManagerOwnerAuthorizationFailurePayload `
            -ManagerAction $ManagerAction `
            -ReasonCode $reason `
            -EvidencePath $EvidencePath
        Write-ManagerJson -Payload $payload -Path $Path | Out-Null
        throw "$reason|Protected Hub Manager action requires active Hub owner/admin authorization."
    }
}

function Invoke-ManagedWsl2RuntimeCandidateInstall {
    param([string]$Path = "")

    if (-not $ConfirmInstallRuntimeCandidate) {
        throw "confirm_install_runtime_candidate_required|Hub Manager install-runtime-candidate requires -ConfirmInstallRuntimeCandidate before writing provider config."
    }

    $paths = Ensure-ImmoAppRuntimeLayout
    $policyPath = Join-Path $paths.ConfigRoot "managed_wsl2_runtime_policy.json"
    $configPlanPath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_config_plan.json"
    $registrationPath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_provider_registration.json"
    $detectionPath = Join-Path $paths.LogsRoot "hub_runtime_detection.json"
    $providerPath = Assert-ImmoAppProviderSnapshotPathSafe -Path (Get-ImmoAppHubRuntimeProviderConfigPath) -AllowNonCanonical
    $existingProviderPresent = $false
    $existingProviderMode = ""
    $existingProviderPreserved = $true
    $candidateOverwriteRefused = $false

    if (Test-Path -LiteralPath $providerPath -PathType Leaf) {
        $existingProviderPresent = $true
        try {
            $existingProvider = Get-Content -LiteralPath $providerPath -Raw | ConvertFrom-Json
            $existingProviderMode = [string](Get-ImmoAppObjectValue -Data $existingProvider -Name "provider_mode")
        }
        catch {
            $existingProviderMode = "unreadable"
        }
        if ($existingProviderMode -ne "managed_wsl2_container_runtime_candidate") {
            $candidateOverwriteRefused = $true
            $payload = [ordered]@{
                kind = "immoapp_hub_manager_managed_wsl2_runtime_candidate_install"
                schema_version = 1
                created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
                machine_name = $env:COMPUTERNAME
                runtime_dependency_mode = "managed_wsl2_container_runtime_candidate"
                proof_only = $true
                proof_scope = "registration_only"
                provider_config_path = $providerPath
                existing_provider_present = $existingProviderPresent
                existing_provider_mode = $existingProviderMode
                existing_provider_preserved = $existingProviderPreserved
                candidate_overwrite_refused = $candidateOverwriteRefused
                candidate_registration_status = "NO-GO"
                provider_registration_status = "not_attempted"
                runtime_artifact_status = "NO-GO"
                runtime_start_status = "NO-GO"
                runtime_start_reason_code = "managed_wsl2_runtime_artifact_missing"
                agency_install_status = "NO_GO"
                public_beta_status = "NO_GO"
                proof_result = "NO-GO"
                reason_code = "existing_managed_runtime_provider_refuses_candidate_overwrite"
                recommended_next_action = "Remove or promote the existing managed runtime provider intentionally before installing a proof-only WSL2 candidate."
            }
            if ($Path) {
                Write-ImmoAppSafeJson -Path $Path -Payload $payload -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 12 | Out-Null
            }
            return $payload
        }
    }

    $policyArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "managed_wsl2_runtime_policy.ps1"),
        "-PlanOnly",
        "-OutputJson", $policyPath
    )
    if ($MachineTotalMemoryGb -gt 0) { $policyArgs += @("-MachineTotalMemoryGb", ([string]$MachineTotalMemoryGb)) }
    if ($MachineLogicalProcessors -gt 0) { $policyArgs += @("-MachineLogicalProcessors", ([string]$MachineLogicalProcessors)) }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeProfileJson)) { $policyArgs += @("-RuntimeProfileJson", $RuntimeProfileJson) }
    & powershell @policyArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_policy_generation_failed|Managed WSL2 runtime policy generation failed." }
    $policy = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json

    $configArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "configure_managed_wsl2_runtime.ps1"),
        "-PlanOnly",
        "-OutputJson", $configPlanPath
    )
    if ($MachineTotalMemoryGb -gt 0) { $configArgs += @("-MachineTotalMemoryGb", ([string]$MachineTotalMemoryGb)) }
    if ($MachineLogicalProcessors -gt 0) { $configArgs += @("-MachineLogicalProcessors", ([string]$MachineLogicalProcessors)) }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeProfileJson)) { $configArgs += @("-RuntimeProfileJson", $RuntimeProfileJson) }
    if ($AllowMergeExistingWslConfig) { $configArgs += "-AllowMergeExistingWslConfig" }
    & powershell @configArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_config_plan_failed|Managed WSL2 runtime global config planning failed." }
    $configPlan = Get-Content -LiteralPath $configPlanPath -Raw | ConvertFrom-Json

    $registration = $null
    $registrationStatus = "NO-GO"
    $registrationReasonCode = "wsl_config_plan_not_go"
    if ([string]$policy.policy_result -eq "GO" -and [string]$configPlan.plan_result -eq "GO") {
        $registerArgs = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $PSScriptRoot "register_managed_hub_runtime_provider.ps1"),
            "-RuntimeDependencyMode", "managed_wsl2_container_runtime_candidate",
            "-WslPolicyJsonPath", $policyPath,
            "-WslConfigPlanJsonPath", $configPlanPath,
            "-ConfirmManagedRuntimeProof"
        )
        if ((Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root") {
            $registerArgs += "-AllowTestOnlyPath"
        }
        $registrationText = & powershell @registerArgs
        if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_provider_registration_failed|Managed WSL2 provider registration failed." }
        $registration = ($registrationText | Out-String) | ConvertFrom-Json
        Write-ImmoAppSafeJson -Path $registrationPath -Payload $registration -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 10 | Out-Null
        $registrationStatus = [string]$registration.provider_write_status
        $registrationReasonCode = [string]$registration.reason_code
    }

    $detectionText = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") -OutputJson $detectionPath
    if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_runtime_detection_failed|Managed WSL2 runtime detection failed after candidate registration." }
    $detection = ($detectionText | Out-String) | ConvertFrom-Json
    $candidateStatus = if (
        [string]$registrationStatus -eq "GO" -and
        [string]$detection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_candidate" -and
        [string]$detection.provider_validation_status -eq "valid" -and
        [string]$detection.internal_proof_status -eq "GO"
    ) { "GO" } else { "NO-GO" }

    $runtimeArtifactStatus = "NO-GO"
    $runtimeStartStatus = "NO-GO"
    $payload = [ordered]@{
        kind = "immoapp_hub_manager_managed_wsl2_runtime_candidate_install"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        machine_name = $env:COMPUTERNAME
        runtime_dependency_mode = "managed_wsl2_container_runtime_candidate"
        proof_only = $true
        proof_scope = "registration_only"
        policy_path = $policyPath
        policy_result = [string]$policy.policy_result
        policy_reason_code = [string]$policy.reason_code
        config_plan_path = $configPlanPath
        config_plan_result = [string]$configPlan.plan_result
        config_reason_code = [string]$configPlan.reason_code
        registration_path = $registrationPath
        existing_provider_present = $existingProviderPresent
        existing_provider_mode = $existingProviderMode
        existing_provider_preserved = $existingProviderPreserved
        candidate_overwrite_refused = $candidateOverwriteRefused
        candidate_registration_status = $candidateStatus
        provider_registration_status = $registrationStatus
        provider_registration_reason_code = $registrationReasonCode
        provider_config_path = [string]$detection.provider_config_path
        provider_config_valid = [bool]$detection.provider_config_valid
        provider_config_sha256 = [string](Get-ImmoAppObjectValue -Data $registration -Name "provider_config_sha256_after_write")
        runtime_detection_path = $detectionPath
        runtime_detection = $detection
        runtime_artifact_status = $runtimeArtifactStatus
        runtime_start_status = $runtimeStartStatus
        runtime_start_reason_code = "managed_wsl2_runtime_artifact_missing"
        internal_candidate_status = $candidateStatus
        agency_install_status = "NO_GO"
        public_beta_status = "NO_GO"
        proof_result = if ($runtimeArtifactStatus -eq "GO" -and $runtimeStartStatus -eq "GO") { "GO" } else { "NO-GO" }
        reason_code = if ($candidateStatus -eq "GO") { "managed_wsl2_runtime_candidate_registration_only" } else { "managed_wsl2_runtime_candidate_not_registered" }
        recommended_next_action = "Install a real ImmoApp-managed WSL2/container runtime artifact, then rerun Hub Manager start/status/health."
    }
    if ($Path) {
        Write-ImmoAppSafeJson -Path $Path -Payload $payload -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 12 | Out-Null
    }
    return $payload
}

function Invoke-ManagedWsl2RuntimeCandidateRemoval {
    param([string]$Path = "")

    $paths = Ensure-ImmoAppRuntimeLayout
    $providerPath = Assert-ImmoAppProviderSnapshotPathSafe -Path (Get-ImmoAppHubRuntimeProviderConfigPath) -AllowNonCanonical
    $providerMode = ""
    $providerWasPresent = $false
    if (Test-Path -LiteralPath $providerPath -PathType Leaf) {
        $providerWasPresent = $true
        $provider = Get-Content -LiteralPath $providerPath -Raw | ConvertFrom-Json
        $providerMode = [string](Get-ImmoAppObjectValue -Data $provider -Name "provider_mode")
        if ($providerMode -ne "managed_wsl2_container_runtime_candidate") {
            throw "managed_runtime_provider_not_wsl_candidate|remove-runtime-candidate only removes managed_wsl2_container_runtime_candidate providers."
        }
    }

    $removeText = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "uninstall_managed_hub_runtime_provider.ps1") -ConfirmManagedRuntimeProviderRemoval
    if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_candidate_remove_failed|Managed WSL2 runtime candidate provider removal failed." }
    $removal = ($removeText | Out-String) | ConvertFrom-Json
    $detectionPath = Join-Path $paths.LogsRoot "hub_runtime_detection_after_candidate_removal.json"
    $detectionText = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") -OutputJson $detectionPath
    if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_candidate_remove_detection_failed|Runtime detection failed after candidate provider removal." }
    $detection = ($detectionText | Out-String) | ConvertFrom-Json
    $removedProviderConfig = [bool](Get-ImmoAppObjectValue -Data $removal -Name "removed_provider_config")
    $proofResult = if ([string]$detection.runtime_dependency_mode -ne "managed_wsl2_container_runtime_candidate") { "GO" } else { "NO-GO" }
    $payload = [ordered]@{
        kind = "immoapp_hub_manager_managed_wsl2_runtime_candidate_remove"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        machine_name = $env:COMPUTERNAME
        provider_config_path = $providerPath
        provider_was_present = $providerWasPresent
        provider_mode_before_removal = $providerMode
        removed_provider_config = $removedProviderConfig
        removed_runtime_data = $false
        removed_hub_data = $false
        removed_backups = $false
        removed_hub_identity = $false
        removed_logs = $false
        removed_runtime_artifacts = $false
        runtime_detection_path = $detectionPath
        runtime_detection_after_removal = $detection
        proof_result = $proofResult
        reason_code = if ($proofResult -eq "GO") { "managed_wsl2_runtime_candidate_removed" } else { "managed_wsl2_runtime_candidate_still_active" }
    }
    if ($Path) {
        Write-ImmoAppSafeJson -Path $Path -Payload $payload -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 12 | Out-Null
    }
    return $payload
}

function Resolve-HubManagerPackagedManagedRuntimeRoot {
    $testRoot = [Environment]::GetEnvironmentVariable("IMMOAPP_TEST_PACKAGED_MANAGED_RUNTIME_ROOT")
    if (
        -not [string]::IsNullOrWhiteSpace($testRoot) -and
        [Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1"
    ) {
        $root = [System.IO.Path]::GetFullPath($testRoot)
    } else {
        $appRoot = Split-Path -Parent $PSScriptRoot
        $root = [System.IO.Path]::GetFullPath((Join-Path $appRoot "deployment\managed-runtime"))
    }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "packaged_managed_runtime_payload_missing|Installed Hub package is missing deployment\managed-runtime payload."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $root) {
        throw "packaged_managed_runtime_payload_reparse_point|Installed managed runtime payload contains a reparse point, symlink, or junction."
    }
    return $root
}

function Resolve-HubManagerPackagedRuntimePath {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$Directory
    )
    $rootFull = [System.IO.Path]::GetFullPath($PackageRoot).TrimEnd("\", "/")
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $PackageRoot $RelativePath))
    if (-not $candidate.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label path escapes the installed managed runtime payload root."
    }
    $pathType = if ($Directory) { "Container" } else { "Leaf" }
    if (-not (Test-Path -LiteralPath $candidate -PathType $pathType)) {
        throw "$Label missing from installed managed runtime payload: $RelativePath"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $candidate) {
        throw "$Label contains a reparse point, symlink, or junction."
    }
    return $candidate
}

function Test-HubManagerManagedWsl2DistroPresent {
    $wslPath = Join-Path $env:WINDIR "System32\wsl.exe"
    $testWslPath = [Environment]::GetEnvironmentVariable("IMMOAPP_TEST_WSL_EXE")
    if (
        -not [string]::IsNullOrWhiteSpace($testWslPath) -and
        [Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1"
    ) {
        $wslPath = [System.IO.Path]::GetFullPath($testWslPath)
    }
    if (-not (Test-Path -LiteralPath $wslPath -PathType Leaf)) {
        return $false
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $wslPath) {
        throw "managed_wsl2_wsl_executable_reparse_point|The approved WSL executable path is a reparse point."
    }
    $text = (& $wslPath -l -q 2>$null | Out-String).Replace([string][char]0, "")
    if ($LASTEXITCODE -ne 0) {
        throw "managed_wsl2_runtime_distro_list_failed|Unable to list WSL distributions."
    }
    $distros = @(
        $text -split "(`r`n|`n|`r)" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { [string]$_.Trim() }
    )
    return ($distros -contains "ImmoAppRuntime")
}

function Update-HubManagerExistingManagedWsl2RuntimePayload {
    param([Parameter(Mandatory = $true)][string]$RootfsPath)
    $paths = Ensure-ImmoAppRuntimeLayout
    $outputPath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_payload_update.json"
    $args = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "import_managed_wsl2_runtime_distro.ps1"),
        "-RootfsTarPath", $RootfsPath,
        "-UpdateExistingRuntimePayload",
        "-ConfirmUpdateExistingRuntimePayload",
        "-OutputJson", $outputPath
    )
    $text = & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "managed_wsl2_runtime_payload_update_failed|Existing ImmoAppRuntime payload update failed: $($text | Out-String)"
    }
    $payload = Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $payload -Name "proof_result") -ne "GO" -or
        [string](Get-ImmoAppObjectValue -Data $payload -Name "payload_update_status") -ne "GO") {
        throw "managed_wsl2_runtime_payload_update_not_go|Existing ImmoAppRuntime payload update did not return GO."
    }
    return $payload
}

function Import-HubManagerManagedWsl2RuntimeDistro {
    param([Parameter(Mandatory = $true)][string]$RootfsPath)
    $paths = Ensure-ImmoAppRuntimeLayout
    $outputPath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_import_plan.json"
    $args = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "import_managed_wsl2_runtime_distro.ps1"),
        "-RootfsTarPath", $RootfsPath,
        "-ConfirmImportManagedWslRuntime",
        "-OutputJson", $outputPath
    )
    $text = & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "managed_wsl2_runtime_import_failed|ImmoAppRuntime import failed: $($text | Out-String)"
    }
    $payload = Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $payload -Name "proof_result") -ne "GO" -or
        [string](Get-ImmoAppObjectValue -Data $payload -Name "import_status") -ne "GO") {
        throw "managed_wsl2_runtime_import_not_go|ImmoAppRuntime import did not return GO."
    }
    return $payload
}

function Copy-HubManagerPackagedRuntimeFile {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$ApprovedRoots
    )
    $source = Resolve-HubManagerPackagedRuntimePath -PackageRoot $PackageRoot -RelativePath $RelativePath -Label $Label
    $destination = [System.IO.Path]::GetFullPath($DestinationPath)
    Assert-ImmoAppProofOnlyPathApproved -Path $destination -Roots $ApprovedRoots -Label $Label
    $parent = Split-Path -Parent $destination
    if (Test-Path -LiteralPath $parent -PathType Container) {
        if (Test-ImmoAppPathHasReparsePoint -Path $parent) {
            throw "$Label destination parent contains a reparse point, symlink, or junction."
        }
    } else {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $destination -Force
    if ((Get-ImmoAppFileSha256 -Path $source) -ne (Get-ImmoAppFileSha256 -Path $destination)) {
        throw "$Label hash mismatch after staging packaged managed runtime payload."
    }
    return $destination
}

function Copy-HubManagerPackagedRuntimeDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$DestinationRoot,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$ApprovedRoots
    )
    $sourceRoot = Resolve-HubManagerPackagedRuntimePath -PackageRoot $PackageRoot -RelativePath $RelativePath -Label $Label -Directory
    $destinationRootFull = [System.IO.Path]::GetFullPath($DestinationRoot)
    Assert-ImmoAppProofOnlyPathApproved -Path $destinationRootFull -Roots $ApprovedRoots -Label $Label
    if (Test-Path -LiteralPath $destinationRootFull -PathType Container) {
        if (Test-ImmoAppPathHasReparsePoint -Path $destinationRootFull) {
            throw "$Label destination contains a reparse point, symlink, or junction."
        }
        Remove-Item -LiteralPath $destinationRootFull -Recurse -Force
    }
    New-Item -ItemType Directory -Path $destinationRootFull -Force | Out-Null
    $sourceTree = Get-ImmoAppStrictRuntimeTreeInventory -Root $sourceRoot -RequireNonEmpty
    foreach ($file in @($sourceTree.files)) {
        $relative = [string]$file.path
        $source = Join-Path $sourceRoot ($relative.Replace("/", "\"))
        $destination = Join-Path $destinationRootFull ($relative.Replace("/", "\"))
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
    return $destinationRootFull
}

function Assert-HubManagerStagedRootfsPayload {
    param(
        [Parameter(Mandatory = $true)][string]$RootfsPath,
        [Parameter(Mandatory = $true)][string]$RootfsInventoryPath
    )
    $inventory = Get-Content -LiteralPath $RootfsInventoryPath -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $inventory -Name "kind") -ne "immoapp_managed_wsl2_runtime_rootfs_inventory" -or
        [string](Get-ImmoAppObjectValue -Data $inventory -Name "proof_result") -ne "GO") {
        throw "packaged_managed_runtime_rootfs_inventory_not_go|Packaged rootfs inventory must be GO."
    }
    $expectedSha = [string](Get-ImmoAppObjectValue -Data $inventory -Name "output_rootfs_tar_sha256")
    Assert-ImmoAppLowerHexSha256 -Value $expectedSha -Name "output_rootfs_tar_sha256"
    if ((Get-ImmoAppFileSha256 -Path $RootfsPath) -ne $expectedSha) {
        throw "packaged_managed_runtime_rootfs_hash_mismatch|Packaged rootfs hash does not match inventory."
    }
    return $inventory
}

function Install-HubManagerPackagedManagedWsl2Payload {
    $paths = Ensure-ImmoAppRuntimeLayout
    $canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
    $allowTestOnlyPath = ((Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root")
    $runtimeRoots = if ($allowTestOnlyPath) {
        Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
    } else {
        @($canonicalPaths.RuntimeRoot)
    }
    $configRoots = if ($allowTestOnlyPath) {
        Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
    } else {
        @($canonicalPaths.ConfigRoot)
    }

    $packageRoot = Resolve-HubManagerPackagedManagedRuntimeRoot
    $rootfsPath = Copy-HubManagerPackagedRuntimeFile -PackageRoot $packageRoot -RelativePath "rootfs\ImmoAppRuntime.rootfs.tar" -DestinationPath (Get-ImmoAppManagedWsl2RootfsTarPath) -Label "RootfsTarPath" -ApprovedRoots $runtimeRoots
    $rootfsInventoryPath = Copy-HubManagerPackagedRuntimeFile -PackageRoot $packageRoot -RelativePath "config\managed_wsl2_runtime_rootfs_inventory.json" -DestinationPath (Get-ImmoAppManagedWsl2RootfsInventoryPath) -Label "RootfsInventoryPath" -ApprovedRoots $configRoots
    $imageArchivePath = Copy-HubManagerPackagedRuntimeFile -PackageRoot $packageRoot -RelativePath "images\immoapp-runtime-images.tar" -DestinationPath (Get-ImmoAppManagedWsl2ImageBundleArchivePath) -Label "ImageBundleArchivePath" -ApprovedRoots $runtimeRoots
    $imageInventoryPath = Copy-HubManagerPackagedRuntimeFile -PackageRoot $packageRoot -RelativePath "config\managed_wsl2_runtime_image_bundle_inventory.json" -DestinationPath (Get-ImmoAppManagedWsl2ImageBundleInventoryPath) -Label "ImageBundleInventoryPath" -ApprovedRoots $configRoots
    $artifactRoot = Copy-HubManagerPackagedRuntimeDirectory -PackageRoot $packageRoot -RelativePath "artifact\managed-wsl2-artifact" -DestinationRoot (Join-Path $paths.RuntimeRoot "managed-wsl2-artifact") -Label "RuntimeArtifactRoot" -ApprovedRoots $runtimeRoots
    $artifactInventoryPath = Copy-HubManagerPackagedRuntimeFile -PackageRoot $packageRoot -RelativePath "config\managed_wsl2_runtime_artifact_inventory.json" -DestinationPath (Join-Path $paths.ConfigRoot "managed_wsl2_runtime_artifact_inventory.json") -Label "RuntimeArtifactInventoryPath" -ApprovedRoots $configRoots

    $rootfsInventory = Assert-HubManagerStagedRootfsPayload -RootfsPath $rootfsPath -RootfsInventoryPath $rootfsInventoryPath
    $existingDistroPresent = Test-HubManagerManagedWsl2DistroPresent
    $runtimeImport = $null
    $runtimeImportStatus = "not_applicable"
    $runtimeImportPath = ""
    $payloadUpdate = $null
    $payloadUpdateStatus = "not_applicable"
    $payloadUpdatePath = ""
    if ($existingDistroPresent) {
        $payloadUpdate = Update-HubManagerExistingManagedWsl2RuntimePayload -RootfsPath $rootfsPath
        $payloadUpdateStatus = [string](Get-ImmoAppObjectValue -Data $payloadUpdate -Name "payload_update_status")
        $payloadUpdatePath = [string](Join-Path $paths.LogsRoot "managed_wsl2_runtime_payload_update.json")
    }
    else {
        $runtimeImport = Import-HubManagerManagedWsl2RuntimeDistro -RootfsPath $rootfsPath
        $runtimeImportStatus = [string](Get-ImmoAppObjectValue -Data $runtimeImport -Name "import_status")
        $runtimeImportPath = [string](Join-Path $paths.LogsRoot "managed_wsl2_runtime_import_plan.json")
    }
    $imageInventorySha = Get-ImmoAppFileSha256 -Path $imageInventoryPath
    $imageInventory = Get-Content -LiteralPath $imageInventoryPath -Raw | ConvertFrom-Json
    Assert-ImmoAppManagedWsl2ImageBundleInventoryReady -Inventory $imageInventory -ExpectedInventorySha256 $imageInventorySha -ImageBundleInventoryPath $imageInventoryPath -AllowTestOnlyPath:$allowTestOnlyPath | Out-Null
    $artifactInventorySha = Get-ImmoAppFileSha256 -Path $artifactInventoryPath
    $artifactInventory = Get-Content -LiteralPath $artifactInventoryPath -Raw | ConvertFrom-Json
    Assert-ImmoAppManagedWsl2RuntimeArtifactInventoryReady -Inventory $artifactInventory -ExpectedInventorySha256 $artifactInventorySha -ArtifactInventoryPath $artifactInventoryPath -AllowTestOnlyPath:$allowTestOnlyPath | Out-Null

    return [ordered]@{
        packaged_payload_status = "GO"
        packaged_payload_root = $packageRoot
        rootfs_path = $rootfsPath
        rootfs_inventory_path = $rootfsInventoryPath
        rootfs_sha256 = [string](Get-ImmoAppObjectValue -Data $rootfsInventory -Name "output_rootfs_tar_sha256")
        existing_distro_present = $existingDistroPresent
        runtime_import_status = $runtimeImportStatus
        runtime_import_path = $runtimeImportPath
        runtime_payload_update_status = $payloadUpdateStatus
        runtime_payload_update_path = $payloadUpdatePath
        runtime_was_running = if ($payloadUpdate) {
            [bool](Get-ImmoAppObjectValue -Data $payloadUpdate -Name "runtime_was_running")
        } else {
            $false
        }
        image_bundle_archive_path = $imageArchivePath
        image_bundle_inventory_path = $imageInventoryPath
        image_bundle_archive_sha256 = [string](Get-ImmoAppObjectValue -Data $imageInventory -Name "image_archive_sha256")
        artifact_root = $artifactRoot
        artifact_inventory_path = $artifactInventoryPath
        artifact_inventory_sha256 = $artifactInventorySha
        artifact_inventory = $artifactInventory
    }
}

function Invoke-ManagedWsl2RuntimeArtifactInstall {
    param([string]$Path = "")

    if (-not $ConfirmInstallRuntimeArtifact) {
        throw "confirm_install_runtime_artifact_required|Hub Manager install-runtime-artifact requires -ConfirmInstallRuntimeArtifact before writing provider config."
    }

    $paths = Ensure-ImmoAppRuntimeLayout
    $policyPath = Join-Path $paths.ConfigRoot "managed_wsl2_runtime_policy.json"
    $configPlanPath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_config_plan.json"
    $artifactInventoryPath = Join-Path $paths.ConfigRoot "managed_wsl2_runtime_artifact_inventory.json"
    $registrationPath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_artifact_provider_registration.json"
    $detectionPath = Join-Path $paths.LogsRoot "hub_runtime_detection_managed_wsl2_artifact.json"

    $policyArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "managed_wsl2_runtime_policy.ps1"),
        "-PlanOnly",
        "-OutputJson", $policyPath
    )
    if ($MachineTotalMemoryGb -gt 0) { $policyArgs += @("-MachineTotalMemoryGb", ([string]$MachineTotalMemoryGb)) }
    if ($MachineLogicalProcessors -gt 0) { $policyArgs += @("-MachineLogicalProcessors", ([string]$MachineLogicalProcessors)) }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeProfileJson)) { $policyArgs += @("-RuntimeProfileJson", $RuntimeProfileJson) }
    & powershell @policyArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_policy_generation_failed|Managed WSL2 runtime policy generation failed." }
    $policy = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json

    $configArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "configure_managed_wsl2_runtime.ps1"),
        "-PlanOnly",
        "-OutputJson", $configPlanPath
    )
    if ($MachineTotalMemoryGb -gt 0) { $configArgs += @("-MachineTotalMemoryGb", ([string]$MachineTotalMemoryGb)) }
    if ($MachineLogicalProcessors -gt 0) { $configArgs += @("-MachineLogicalProcessors", ([string]$MachineLogicalProcessors)) }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeProfileJson)) { $configArgs += @("-RuntimeProfileJson", $RuntimeProfileJson) }
    if ($AllowMergeExistingWslConfig) { $configArgs += "-AllowMergeExistingWslConfig" }
    & powershell @configArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_config_plan_failed|Managed WSL2 runtime global config planning failed." }
    $configPlan = Get-Content -LiteralPath $configPlanPath -Raw | ConvertFrom-Json

    $packagedPayload = Install-HubManagerPackagedManagedWsl2Payload
    $artifactInventory = $packagedPayload.artifact_inventory
    $runtimeRestartRequired = [bool]$packagedPayload.runtime_was_running
    $runtimeRestartStatus = if ($runtimeRestartRequired) { "NO-GO" } else { "not_required" }
    $runtimeRestartPath = ""
    $runtimeRestartReason = ""

    $registration = $null
    $registrationStatus = "NO-GO"
    $registrationReasonCode = "wsl_or_artifact_not_go"
    if (
        [string]$policy.policy_result -eq "GO" -and
        [string]$configPlan.plan_result -eq "GO" -and
        [string]$artifactInventory.proof_result -eq "GO"
    ) {
        $registerArgs = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $PSScriptRoot "register_managed_hub_runtime_provider.ps1"),
            "-RuntimeDependencyMode", "managed_wsl2_container_runtime_artifact",
            "-WslPolicyJsonPath", $policyPath,
            "-WslConfigPlanJsonPath", $configPlanPath,
            "-RuntimeArtifactInventoryJson", $artifactInventoryPath,
            "-ConfirmManagedRuntimeProof"
        )
        if ((Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root") {
            $registerArgs += "-AllowTestOnlyPath"
        }
        $registrationText = & powershell @registerArgs
        if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_artifact_provider_registration_failed|Managed WSL2 artifact provider registration failed." }
        $registration = ($registrationText | Out-String) | ConvertFrom-Json
        Write-ImmoAppSafeJson -Path $registrationPath -Payload $registration -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 12 | Out-Null
        $registrationStatus = [string]$registration.provider_write_status
        $registrationReasonCode = [string]$registration.reason_code
    }

    if ($runtimeRestartRequired -and $registrationStatus -eq "GO") {
        $runtimeRestartPath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_payload_update_restart.json"
        try {
            $runtimeRestart = Invoke-ManagedWsl2RuntimeArtifactAction `
                -ManagedAction "start" `
                -Path $runtimeRestartPath
            $runtimeRestartStatus = if (
                [string](Get-ImmoAppObjectValue -Data $runtimeRestart -Name "proof_result") -eq "GO"
            ) { "GO" } else { "NO-GO" }
        }
        catch {
            $runtimeRestartStatus = "NO-GO"
            $runtimeRestartReason = [string]$_.Exception.Message
        }
    }

    $detectionText = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") -OutputJson $detectionPath
    if ($LASTEXITCODE -ne 0) { throw "managed_wsl2_runtime_detection_failed|Managed WSL2 runtime detection failed after artifact registration." }
    $detection = ($detectionText | Out-String) | ConvertFrom-Json
    $artifactStatus = if (
        [string]$registrationStatus -eq "GO" -and
        [string]$detection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact" -and
        [string]$detection.runtime_artifact_status -eq "GO" -and
        [string]$detection.provider_validation_status -eq "valid"
    ) { "GO" } else { "NO-GO" }

    $payload = [ordered]@{
        kind = "immoapp_hub_manager_managed_wsl2_runtime_artifact_install"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        machine_name = $env:COMPUTERNAME
        runtime_dependency_mode = "managed_wsl2_container_runtime_artifact"
        policy_path = $policyPath
        policy_result = [string]$policy.policy_result
        config_plan_path = $configPlanPath
        config_plan_result = [string]$configPlan.plan_result
        packaged_payload_status = [string]$packagedPayload.packaged_payload_status
        packaged_payload_root = [string]$packagedPayload.packaged_payload_root
        rootfs_path = [string]$packagedPayload.rootfs_path
        rootfs_inventory_path = [string]$packagedPayload.rootfs_inventory_path
        rootfs_sha256 = [string]$packagedPayload.rootfs_sha256
        existing_distro_present = [bool]$packagedPayload.existing_distro_present
        runtime_import_status = [string]$packagedPayload.runtime_import_status
        runtime_import_path = [string]$packagedPayload.runtime_import_path
        runtime_payload_update_status = [string]$packagedPayload.runtime_payload_update_status
        runtime_payload_update_path = [string]$packagedPayload.runtime_payload_update_path
        runtime_was_running = [bool]$packagedPayload.runtime_was_running
        runtime_restart_required = $runtimeRestartRequired
        runtime_restart_status = $runtimeRestartStatus
        runtime_restart_path = $runtimeRestartPath
        runtime_restart_reason = $runtimeRestartReason
        artifact_inventory_path = $artifactInventoryPath
        artifact_inventory_sha256 = Get-ImmoAppFileSha256 -Path $artifactInventoryPath
        staged_artifact_root = [string]$packagedPayload.artifact_root
        image_bundle_archive_path = [string]$packagedPayload.image_bundle_archive_path
        image_bundle_inventory_path = [string]$packagedPayload.image_bundle_inventory_path
        image_bundle_archive_sha256 = [string]$packagedPayload.image_bundle_archive_sha256
        compose_payload_path = [string](Get-ImmoAppObjectValue -Data $artifactInventory -Name "compose_payload_path")
        compose_pull_policy = [string](Get-ImmoAppObjectValue -Data $artifactInventory -Name "compose_pull_policy")
        runtime_artifact_status = $artifactStatus
        provider_registration_status = $registrationStatus
        provider_registration_reason_code = $registrationReasonCode
        registration_path = $registrationPath
        provider_config_path = [string]$detection.provider_config_path
        provider_config_valid = [bool]$detection.provider_config_valid
        provider_config_sha256 = [string](Get-ImmoAppObjectValue -Data $registration -Name "provider_config_sha256_after_write")
        runtime_detection_path = $detectionPath
        runtime_detection = $detection
        runtime_start_status = if ($runtimeRestartRequired) {
            $runtimeRestartStatus
        } else {
            "NO-GO"
        }
        runtime_start_reason_code = if ($runtimeRestartRequired -and $runtimeRestartStatus -eq "GO") {
            "managed_wsl2_runtime_payload_update_restart_go"
        } elseif ($runtimeRestartRequired) {
            "managed_wsl2_runtime_payload_update_restart_failed"
        } else {
            "managed_wsl2_runtime_start_not_proven"
        }
        internal_proof_status = if ($artifactStatus -eq "GO") { "GO" } else { "NO_GO" }
        agency_install_status = "NO_GO"
        public_beta_status = "NO_GO"
        proof_result = if ($artifactStatus -eq "GO" -and $runtimeRestartStatus -eq "GO") {
            "GO"
        } else {
            "NO-GO"
        }
        reason_code = if ($artifactStatus -ne "GO") {
            "managed_wsl2_runtime_artifact_not_registered"
        } elseif ($runtimeRestartRequired -and $runtimeRestartStatus -eq "GO") {
            "managed_wsl2_runtime_artifact_updated_and_restarted"
        } elseif ($runtimeRestartRequired) {
            "managed_wsl2_runtime_artifact_updated_restart_failed"
        } else {
            "managed_wsl2_runtime_artifact_registered_start_not_proven"
        }
        recommended_next_action = if ($runtimeRestartRequired -and $runtimeRestartStatus -eq "GO") {
            "The updated Hub engine is running."
        } else {
            "Run Hub Manager start/status/health through the managed WSL2 artifact."
        }
    }
    if ($Path) {
        Write-ImmoAppSafeJson -Path $Path -Payload $payload -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 14 | Out-Null
    }
    return $payload
}

function New-HubManagerSetupRunId {
    return ([guid]::NewGuid().ToString("N").ToLowerInvariant())
}

function Resolve-HubManagerPowerShellPath {
    $systemPowerShell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (Test-Path -LiteralPath $systemPowerShell -PathType Leaf) {
        return (Resolve-Path -LiteralPath $systemPowerShell).Path
    }
    $psHomePowerShell = Join-Path $PSHOME "powershell.exe"
    if (Test-Path -LiteralPath $psHomePowerShell -PathType Leaf) {
        return (Resolve-Path -LiteralPath $psHomePowerShell).Path
    }
    throw "Windows PowerShell executable was not found."
}

function Quote-WindowsCommandLineArgument {
    param([AllowNull()][string]$Argument)
    if ($null -eq $Argument) { return '""' }
    if ($Argument -notmatch '[\s"]') { return $Argument }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($char in $Argument.ToCharArray()) {
        if ($char -eq "\") {
            $backslashes += 1
            continue
        }
        if ($char -eq '"') {
            if ($backslashes -gt 0) { [void]$builder.Append("\" * ($backslashes * 2)) }
            [void]$builder.Append('\"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append("\" * $backslashes)
            $backslashes = 0
        }
        [void]$builder.Append($char)
    }
    if ($backslashes -gt 0) { [void]$builder.Append("\" * ($backslashes * 2)) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Join-WindowsCommandLineArguments {
    param([string[]]$Arguments = @())
    return (@($Arguments | ForEach-Object { Quote-WindowsCommandLineArgument -Argument $_ }) -join " ")
}

Assert-HubManagerGenericOwnerAuthorization `
    -ManagerAction $Action `
    -EvidencePath $OwnerAuthorizationEvidenceJson `
    -Path $OutputJson `
    -HubBaseUrl $HubBaseUrl

switch ($Action) {
    "start" {
        Invoke-StackAction -StackAction "up" -Path $OutputJson
    }
    "stop" {
        Invoke-StackAction -StackAction "down" -Path $OutputJson
    }
    "restart" {
        Invoke-StackAction -StackAction "restart-app" -Path $OutputJson
    }
    "status" {
        $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "hub_status_evidence.json" }
        $runtimeDetection = Resolve-ImmoAppHubRuntimeDetection
        if ([string]$runtimeDetection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact") {
            $managedTarget = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "managed_wsl2_runtime_status_evidence.json" }
            $payload = $null
            try {
                $payload = Invoke-ManagedWsl2RuntimeArtifactAction -ManagedAction "status" -Path $managedTarget
            }
            catch {
                if (Test-Path -LiteralPath $managedTarget -PathType Leaf) {
                    $payload = Get-Content -LiteralPath $managedTarget -Raw | ConvertFrom-Json
                }
                else {
                    throw
                }
            }
            $payload = Add-HubManagerLocalStateToPayload -Payload $payload
            $paths = Ensure-ImmoAppRuntimeLayout
            Write-ImmoAppSafeJson `
                -Path $managedTarget `
                -Payload $payload `
                -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) `
                -Depth 20 | Out-Null
            Write-Host "Managed WSL2 runtime status: $($payload.runtime_command_status); front door: $($payload.front_door_health_status)"
            Write-Host "Technical details JSON: $managedTarget"
            return
        }
        $statusArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "collect_hub_status_evidence.ps1"), "-OutputJson", $target)
        if ($HubBaseUrl) { $statusArgs += @("-HubBaseUrl", $HubBaseUrl) }
        & powershell @statusArgs
        if ($LASTEXITCODE -ne 0) { throw "Hub status evidence collection failed." }
        if (Test-Path -LiteralPath $target) {
            $payload = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
            $displayName = [string](Get-ImmoAppObjectValue -Data $payload -Name "hub_display_name")
            if ([string]::IsNullOrWhiteSpace($displayName)) { $displayName = Get-HubDisplayNameForManager }
            if ([string]::IsNullOrWhiteSpace($displayName)) { $displayName = "Office Hub" }
            Write-Host "$displayName status: $($payload.hub_status)"
            Write-Host "Technical details JSON: $target"
        }
    }
    "health" {
        $runtimeDetection = Resolve-ImmoAppHubRuntimeDetection
        if ([string]$runtimeDetection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact") {
            $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "managed_wsl2_runtime_health_evidence.json" }
            $payload = $null
            try {
                $payload = Invoke-ManagedWsl2RuntimeArtifactAction -ManagedAction "health" -Path $target
            }
            catch {
                if (Test-Path -LiteralPath $target -PathType Leaf) {
                    $payload = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
                }
                else {
                    throw
                }
            }
            Write-Host "Managed WSL2 runtime health: $($payload.front_door_health_status); HTTP $($payload.health_status)"
            Write-Host "Technical details JSON: $target"
            if ($payload.proof_result -ne "GO") { exit 1 }
            return
        }
        $base = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { Get-ImmoAppHubBaseUrl -PreferLan }
        $healthUrl = "$base/api/v1/health/"
        $response = Invoke-WebRequest -Method Get -Uri $healthUrl -TimeoutSec 8 -UseBasicParsing
        Write-Host "Hub health: HTTP $([int]$response.StatusCode) $healthUrl"
    }
    "logs" {
        Invoke-StackAction -StackAction "logs" -Path $OutputJson
    }
    "support" {
        $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "collect_desktop_support_bundle.ps1"))
        if ($OutputJson) {
            $outputDir = Split-Path -Parent $OutputJson
            if ($outputDir) { $args += @("-OutputDir", $outputDir) }
        }
        & powershell @args
        if ($LASTEXITCODE -ne 0) { throw "Support bundle collection failed." }
    }
    "backup-now" {
        $runtimeDetection = Resolve-ImmoAppHubRuntimeDetection
        if ([string]$runtimeDetection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact") {
            $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "managed_wsl2_runtime_backup_evidence.json" }
            $payload = Invoke-ManagedWsl2RuntimeArtifactAction -ManagedAction "backup" -Path $target
            Write-Host "Managed WSL2 runtime backup: $($payload.backup_status)"
            Write-Host "Backup bundle: $($payload.backup_bundle_path)"
            Write-Host "Technical details JSON: $target"
            return
        }
        $scriptSource = Get-ImmoAppCurrentScriptRootSource
        if ($scriptSource -in @("installed_app", "installed_programdata")) {
            throw "managed_runtime_provider_missing|Installed Hub Manager requires an ImmoApp-managed runtime provider for backup. It will not run repo/dev backup scripts from an installed package."
        }
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "backup_release_bundle.ps1")
        if ($LASTEXITCODE -ne 0) { throw "Backup-now failed." }
    }
    "open-desktop" {
        $desktop = Resolve-ImmoAppDesktopExecutable
        if (-not (Test-ImmoAppInstalledSource -Source ([string]$desktop.source)) -or -not (Test-Path -LiteralPath ([string]$desktop.path) -PathType Leaf)) {
            throw "ImmoApp Desktop is not installed on this computer. Install Desktop or use Hub-only manager actions."
        }
        $exe = [string]$desktop.path
        Start-Process -FilePath $exe
        Write-Host "Opened ImmoApp Desktop: $exe"
    }
    "copy-url" {
        $base = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { Get-ImmoAppHubBaseUrl -PreferLan }
        Set-Clipboard -Value $base
        Write-Host "Copied Hub URL: $base"
    }
    "identity" {
        $identity = Read-ImmoAppHubIdentity
        $state = Get-ImmoAppHubStateSummary
        $payload = [ordered]@{
            kind = "immoapp_hub_manager_identity"
            schema_version = 1
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            hub_id = [string]$identity.hub_id
            hub_display_name = [string]$identity.hub_display_name
            hub_identity_path = [string]$identity.path
            hub_state_manifest_status = [string]$state.hub_state_manifest_status
            hub_state_manifest_path = [string]$state.hub_state_manifest_path
            technical_details = [ordered]@{
                machine_hostname_readonly = [string]$identity.data.machine_hostname_readonly
                source = [string]$identity.data.source
            }
        }
        Write-Host "Hub name: $($payload.hub_display_name)"
        Write-ManagerJson -Payload $payload -Path $OutputJson
    }
    "front-door" {
        $base = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { Get-ImmoAppHubBaseUrl -PreferLan }
        $payload = [ordered]@{
            kind = "immoapp_hub_manager_front_door"
            schema_version = 1
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            hub_display_name = Get-HubDisplayNameForManager
            front_door_url = $base
            front_door_port = Get-ImmoAppHubPort
            front_door_service = "caddy"
            technical_details = [ordered]@{
                machine_hostname_readonly = $env:COMPUTERNAME
            }
        }
        Write-Host "Hub front door: $($payload.front_door_url)"
        Write-ManagerJson -Payload $payload -Path $OutputJson
    }
    "runtime-status" {
        $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "hub_runtime_detection.json" }
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") -OutputJson $target | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Hub runtime status detection failed." }
        $payload = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
        Write-Host "Runtime mode: $($payload.runtime_dependency_mode); agency status: $($payload.agency_install_status)"
    }
    "install-runtime-candidate" {
        $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "managed_wsl2_runtime_candidate_install.json" }
        $payload = Invoke-ManagedWsl2RuntimeCandidateInstall -Path $target
        Write-Host "Managed WSL2 runtime candidate registration: $($payload.candidate_registration_status)"
        Write-Host "Runtime artifact: $($payload.runtime_artifact_status); start: $($payload.runtime_start_status)"
        Write-Host "Agency status: $($payload.agency_install_status)"
        Write-Host "Evidence JSON: $target"
        Write-ManagerJson -Payload $payload
        if ($payload.candidate_registration_status -ne "GO") { exit 1 }
    }
    "install-runtime-artifact" {
        $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "managed_wsl2_runtime_artifact_install.json" }
        $payload = Invoke-ManagedWsl2RuntimeArtifactInstall -Path $target
        Write-Host "Managed WSL2 runtime artifact: $($payload.runtime_artifact_status)"
        Write-Host "Runtime start: $($payload.runtime_start_status)"
        Write-Host "Agency status: $($payload.agency_install_status)"
        Write-Host "Evidence JSON: $target"
        Write-ManagerJson -Payload $payload
        if (
            $payload.runtime_artifact_status -ne "GO" -or
            ($payload.runtime_restart_required -and $payload.runtime_restart_status -ne "GO")
        ) { exit 1 }
    }
    "remove-runtime-candidate" {
        $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "managed_wsl2_runtime_candidate_remove.json" }
        $payload = Invoke-ManagedWsl2RuntimeCandidateRemoval -Path $target
        Write-Host "Managed WSL2 runtime candidate removal: $($payload.proof_result)"
        Write-Host "Removed provider config: $($payload.removed_provider_config)"
        Write-Host "Evidence JSON: $target"
        Write-ManagerJson -Payload $payload
        if ($payload.proof_result -ne "GO") { exit 1 }
    }
    "cleanup-runtime-logs" {
        $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "managed_runtime_log_retention.json" }
        $payload = Invoke-ImmoAppManagedRuntimeLogRetention -OutputJson $target -RetentionDays $RetentionDays -MaxTotalBytes $MaxTotalBytes
        Write-Host "Managed runtime log retention: $($payload.proof_result)"
        Write-Host "Deleted files: $($payload.deleted_file_count); retained bytes: $($payload.retained_bytes)"
        Write-Host "Evidence JSON: $target"
        Write-ManagerJson -Payload $payload
        if ($payload.proof_result -ne "GO") { exit 1 }
    }
    "delete-hub-data" {
        $target = if ($OutputJson) { $OutputJson } else { Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "hub_data_deletion_evidence.json" }
        $payload = Invoke-ImmoAppHubDataDeletion `
            -OutputJson $target `
            -OwnerAuthorizationEvidenceJson $OwnerAuthorizationEvidenceJson `
            -HubBaseUrl $HubBaseUrl `
            -TypedConfirmation $TypedConfirmation `
            -ConfirmDeleteHubData:$ConfirmDeleteHubData `
            -StopRuntime { Invoke-StackAction -StackAction "down" }
        Write-Host "Hub data deletion: $($payload.proof_result)"
        Write-Host "Reason: $($payload.reason_code)"
        Write-Host "Evidence JSON: $target"
        Write-ManagerJson -Payload $payload
        if ($payload.proof_result -ne "GO") { exit 1 }
    }
    "firewall-status" {
        $ruleName = "ImmoApp Office Hub Front Door"
        $firewall = Get-ImmoAppHubFirewallRuleEvidence -RuleName $ruleName -Port (Get-ImmoAppHubPort)
        $payload = [ordered]@{
            kind = "immoapp_hub_manager_firewall_status"
            schema_version = 1
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            firewall_rule_name = [string]$firewall.rule_name
            firewall_status = [string]$firewall.status
            front_door_port = if ([string]::IsNullOrWhiteSpace([string]$firewall.local_port)) { Get-ImmoAppHubPort } else { [int]$firewall.local_port }
            profile = [string]$firewall.profile
            firewall = $firewall
        }
        Write-Host "Firewall rule: $($payload.firewall_status) ($ruleName)"
        Write-ManagerJson -Payload $payload -Path $OutputJson
    }
    "connection-details" {
        $base = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { Get-ImmoAppHubBaseUrl -PreferLan }
        $payload = [ordered]@{
            kind = "immoapp_hub_manager_connection_details"
            schema_version = 1
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            hub_display_name = Get-HubDisplayNameForManager
            front_door_url = $base
            proof_scope = "technical_details"
            technical_details = [ordered]@{
                machine_hostname_readonly = $env:COMPUTERNAME
                front_door_port = Get-ImmoAppHubPort
            }
        }
        Write-Host "Connection name: $($payload.hub_display_name)"
        Write-Host "Technical details JSON: $OutputJson"
        Write-ManagerJson -Payload $payload -Path $OutputJson
    }
    "rename-hub" {
        if ([string]::IsNullOrWhiteSpace($HubDisplayName)) {
            if ($Host.Name -match "ConsoleHost") {
                $HubDisplayName = Read-Host "Hub name"
            }
            if ([string]::IsNullOrWhiteSpace($HubDisplayName)) {
                throw "rename-hub requires -HubDisplayName. $(Get-ImmoAppHubIdentityDisplayNameHelp)"
            }
        }
        $result = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "set_hub_identity.ps1") -HubDisplayName $HubDisplayName -Source hub_manager
        if ($LASTEXITCODE -ne 0) { throw "Hub rename failed." }
        Write-Host "Hub renamed: $HubDisplayName"
        if ($OutputJson) {
            $paths = Ensure-ImmoAppRuntimeLayout
            $parsed = (($result | Out-String) | ConvertFrom-Json)
            Write-ImmoAppSafeJson -Path $OutputJson -Payload $parsed -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) | Out-Null
        }
    }
    "finish-hub-setup" {
        $identity = $null
        try {
            $identity = Read-ImmoAppHubIdentity
        }
        catch {
            throw "Finish Hub setup requires a saved Hub name first. Open Hub Manager and choose Rename Hub, or rerun the installer Hub setup step."
        }
        $hubName = [string]$identity.hub_display_name
        if ([string]::IsNullOrWhiteSpace($hubName)) {
            throw "Finish Hub setup requires a saved Hub name first. Open Hub Manager and choose Rename Hub, or rerun the installer Hub setup step."
        }
        $paths = Ensure-ImmoAppRuntimeLayout
        $setupRunId = New-HubManagerSetupRunId
        $evidencePath = Join-Path $paths.LogsRoot "hub_installer_foundation_evidence.json"
        $setupScript = Join-Path $PSScriptRoot "setup_office_hub.ps1"
        $desktop = Resolve-ImmoAppDesktopExecutable
        $desktopInstalled = Test-ImmoAppInstalledSource -Source ([string]$desktop.source)
        $installMode = if ($desktopInstalled) { "desktop_and_hub" } else { "hub_only" }
        if (Test-Path -LiteralPath $evidencePath) {
            Remove-Item -LiteralPath $evidencePath -Force
        }
        $powerShellPath = Resolve-HubManagerPowerShellPath
        $arguments = Join-WindowsCommandLineArguments -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $setupScript,
            "-Role",
            "HubDesktop",
            "-HubDisplayName",
            $hubName,
            "-CreateFirewallRule",
            "-NoAutoStart",
            "-NoStartHub",
            "-SetupRunId",
            $setupRunId,
            "-SelectedInstallDesktop",
            $(if ($desktopInstalled) { "1" } else { "0" }),
            "-SelectedInstallHub",
            "1",
            "-InstallMode",
            $installMode,
            "-OutputJson",
            $evidencePath
        )
        $result = [ordered]@{
            kind = "immoapp_hub_manager_finish_setup"
            schema_version = 1
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            setup_run_id = $setupRunId
            evidence_path = $evidencePath
            result = "NO-GO"
            failure_reason = ""
            powershell_path = $powerShellPath
            setup_command_line = $arguments
        }
        try {
            $process = Start-Process -FilePath $powerShellPath -ArgumentList $arguments -Verb RunAs -Wait -PassThru
            if ($process.ExitCode -eq 0 -and (Test-Path -LiteralPath $evidencePath)) {
                $evidence = Get-Content -LiteralPath $evidencePath -Raw | ConvertFrom-Json
                if (
                    [string]$evidence.setup_run_id -eq $setupRunId -and
                    [string]$evidence.proof_result -eq "GO" -and
                    [string]$evidence.foundation_applied_status -eq "GO" -and
                    [string]$evidence.hub_foundation_status -eq "GO" -and
                    (Convert-ImmoAppBoolean -Value $evidence.selected_install_hub) -and
                    [string]$evidence.install_mode -eq $installMode
                ) {
                    $result.result = "GO"
                }
                else {
                    $result.failure_reason = "Hub setup evidence was missing GO status for setup_run_id $setupRunId."
                }
            }
            else {
                $result.failure_reason = "Hub setup elevated process failed or evidence was not written."
            }
        }
        catch {
            $result.failure_reason = $_.Exception.Message
        }
        Write-Host "Finish ImmoApp Office Hub Setup: $($result.result)"
        Write-Host "Setup run ID: $setupRunId"
        Write-Host "Evidence: $evidencePath"
        if ($result.failure_reason) { Write-Host "Failure reason: $($result.failure_reason)" }
        Write-ManagerJson -Payload $result -Path $OutputJson
        if ($result.result -ne "GO") { exit 1 }
    }
}
