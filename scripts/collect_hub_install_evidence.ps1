param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("hub_desktop", "workstation_only", "hub_only")]
    [string]$InstallRole,
    [Parameter(Mandatory = $true)][string]$OutputJson,
    [string]$HubBaseUrl = "",
    [string]$DataPath = "",
    [string]$InstallerSha256 = "",
    [string]$SourceCommitSha = "",
    [string]$InstalledVersion = "",
    [string]$InstalledBuildIdentityJson = "",
    [string]$RuntimeDetectionJson = "",
    [string]$RuntimeDependencyMode = "",
    [string]$AgencyInstallStatus = "",
    [string]$StatusEvidenceJson = "",
    [string]$SupportBundlePath = "",
    [string]$FailureReason = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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

function Invoke-HubRuntimeDetection {
    param([Parameter(Mandatory = $true)][string]$OutputJson)
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") -OutputJson $OutputJson
    if ($LASTEXITCODE -ne 0) { throw "Hub runtime detection failed." }
    return (($output | Out-String) | ConvertFrom-Json)
}

if ($InstallRole -eq "workstation_only" -and [string]::IsNullOrWhiteSpace($HubBaseUrl)) {
    throw "Workstation-only install evidence requires explicit HubBaseUrl."
}

$runtimePaths = Ensure-ImmoAppRuntimeLayout
$dataRoot = if ($DataPath) { $DataPath } else { $runtimePaths.AppDataRoot }
$resolvedHubBaseUrl = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { Get-ImmoAppHubBaseUrl -PreferLan }
if ($InstallRole -eq "workstation_only" -and (Test-ImmoAppLocalhostUrl -Url $resolvedHubBaseUrl)) {
    throw "Workstation-only Hub URL must use a Hub IP/hostname, not localhost."
}
$runtimeDetectionPath = if ($RuntimeDetectionJson) { $RuntimeDetectionJson } else { Join-Path $runtimePaths.LogsRoot "hub_runtime_detection.json" }
$runtimeDetection = if (Test-Path -LiteralPath $runtimeDetectionPath) {
    Get-Content -LiteralPath $runtimeDetectionPath -Raw | ConvertFrom-Json
} else {
    Invoke-HubRuntimeDetection -OutputJson $runtimeDetectionPath
}
$runtimeMode = [string]$runtimeDetection.runtime_dependency_mode
$runtimeUserVisible = [bool]$runtimeDetection.runtime_is_user_visible
$runtimeHiddenFromOperator = (
    $runtimeMode -eq "managed_container_runtime" -and
    -not $runtimeUserVisible -and
    [string]$runtimeDetection.provider_validation_status -eq "valid" -and
    [string]$runtimeDetection.agency_install_status -eq "GO"
)
$dockerDesktopDetected = Convert-ImmoAppBoolean (Get-ImmoAppObjectValue -Data $runtimeDetection -Name "docker_desktop_detected")
$manualDockerDesktopInternalOnly = ($runtimeMode -eq "manual_docker_desktop" -or $dockerDesktopDetected)
$hubManagerScript = Resolve-ImmoAppHubManagerScript
$desktopExe = Resolve-ImmoAppDesktopExecutable
$hubIdentity = $null
try { $hubIdentity = Read-ImmoAppHubIdentity -Optional } catch { $hubIdentity = $null }
$preservedDataState = Get-ImmoAppHubPreservedDataStateEvidence
if ([string]::IsNullOrWhiteSpace($RuntimeDependencyMode)) {
    $RuntimeDependencyMode = [string]$runtimeDetection.runtime_dependency_mode
}
if ([string]::IsNullOrWhiteSpace($AgencyInstallStatus)) {
    $AgencyInstallStatus = [string]$runtimeDetection.agency_install_status
}
$statusEvidence = $null
if ($StatusEvidenceJson) {
    if (-not (Test-Path -LiteralPath $StatusEvidenceJson)) {
        throw "Hub status evidence JSON not found: $StatusEvidenceJson"
    }
    $statusEvidence = Get-Content -LiteralPath $StatusEvidenceJson -Raw | ConvertFrom-Json
}
$installedIdentity = $null
if ($InstalledBuildIdentityJson) {
    if (-not (Test-Path -LiteralPath $InstalledBuildIdentityJson)) {
        throw "Installed build identity JSON not found: $InstalledBuildIdentityJson"
    }
    $installedIdentity = Get-Content -LiteralPath $InstalledBuildIdentityJson -Raw | ConvertFrom-Json
}
$supportBundleSha = ""
if ($SupportBundlePath) {
    if (-not (Test-Path -LiteralPath $SupportBundlePath)) {
        throw "Support bundle path not found: $SupportBundlePath"
    }
    $supportBundleSha = Get-FileSha256 -Path $SupportBundlePath
}

$proofGo = $true
$reasons = New-Object System.Collections.Generic.List[string]
if ($RuntimeDependencyMode -eq "manual_docker_desktop") {
    $proofGo = $false
    $reasons.Add("Manual Docker Desktop/runtime use is internal-beta only and is NO-GO for real agency install.")
}
if ($AgencyInstallStatus -ne "GO") {
    $proofGo = $false
    $reasons.Add("Agency install status is $AgencyInstallStatus.")
}
$runtimeProviderProofOnly = [string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "proof_only")
if ([string]$runtimeDetection.provider_validation_status -ne "valid" -or [string]$runtimeDetection.reason_code -ne "managed_runtime_ready") {
    $proofGo = $false
    $reasons.Add("Managed runtime provider validation is not production-ready.")
}
if ($runtimeProviderProofOnly -eq "True" -or $runtimeProviderProofOnly -eq "true") {
    $proofGo = $false
    $reasons.Add("Proof-only managed runtime provider cannot satisfy real agency install.")
}
if (-not (Test-ImmoAppInstalledSource -Source ([string]$hubManagerScript.source))) {
    $proofGo = $false
    $reasons.Add("Hub Manager script source is $($hubManagerScript.source); real agency install requires installed source.")
}
if (-not (Test-ImmoAppInstalledSource -Source ([string]$desktopExe.source))) {
    $proofGo = $false
    $reasons.Add("Desktop executable source is $($desktopExe.source); real agency install requires installed source.")
}
if ($FailureReason) {
    $proofGo = $false
    $reasons.Add($FailureReason)
}

$evidence = [ordered]@{
    kind = "immoapp_hub_install_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    source_commit_sha = Get-GitCommitSha
    installer_sha256 = $InstallerSha256.ToLowerInvariant()
    installed_version = $InstalledVersion
    installed_build_identity = $installedIdentity
    proof_result = if ($proofGo) { "GO" } else { "NO-GO" }
    failure_reason = if ($reasons.Count -gt 0) { $reasons.ToArray() -join " " } else { "" }
    install_role = $InstallRole
    hub_display_name = if ($hubIdentity) { [string]$hubIdentity.hub_display_name } else { "" }
    hub_identity = if ($hubIdentity) { $hubIdentity.data } else { $null }
    product_modes = @("hub_desktop", "workstation_only")
    hub_only_deferred = ($InstallRole -ne "hub_only")
    hub_base_url = $resolvedHubBaseUrl
    hub_front_door_url = $resolvedHubBaseUrl
    backend_url_is_localhost = Test-ImmoAppLocalhostUrl -Url $resolvedHubBaseUrl
    data_path = $dataRoot
    data_preserved_on_uninstall = $true
    full_data_wipe_requires_separate_confirmation = $true
    preserved_hub_data_state_status = [string]$preservedDataState.proof_result
    preserved_hub_data_state = $preservedDataState
    runtime_dependency_mode = $RuntimeDependencyMode
    agency_install_status = $AgencyInstallStatus
    internal_proof_status = [string]$runtimeDetection.internal_proof_status
    runtime_artifact_status = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "runtime_artifact_status")
    runtime_start_status = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "runtime_start_status")
    runtime_start_reason_code = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "runtime_start_reason_code")
    runtime_user_visible = [bool]$runtimeDetection.runtime_is_user_visible
    hub_manager_script_path = [string]$hubManagerScript.path
    hub_manager_script_source = [string]$hubManagerScript.source
    desktop_exe_path = [string]$desktopExe.path
    desktop_exe_source = [string]$desktopExe.source
    proof_scope = if ((Test-ImmoAppInstalledSource -Source ([string]$hubManagerScript.source)) -and (Test-ImmoAppInstalledSource -Source ([string]$desktopExe.source))) { "installed" } else { "dev_internal" }
    runtime_detection_path = $runtimeDetectionPath
    runtime_detection = $runtimeDetection
    runtime_provider_proof = [ordered]@{
        provider_config_path = [string]$runtimeDetection.provider_config_path
        provider_config_present = [bool]$runtimeDetection.provider_config_present
        provider_config_valid = [bool]$runtimeDetection.provider_config_valid
        provider_validation_status = [string]$runtimeDetection.provider_validation_status
        provider_mode = [string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "provider_mode")
        proof_only = [string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "proof_only")
        runtime_user_visible = [bool]$runtimeDetection.runtime_is_user_visible
        internal_proof_status = [string]$runtimeDetection.internal_proof_status
        reason_code = [string]$runtimeDetection.reason_code
        package_inventory_path = [string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "package_inventory_path")
        package_sha256 = [string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "package_sha256")
        provider = $runtimeDetection.provider
    }
    runtime_is_user_visible = $runtimeUserVisible
    runtime_hidden_from_operator = $runtimeHiddenFromOperator
    docker_desktop_detected = $dockerDesktopDetected
    manual_docker_desktop_internal_only = $manualDockerDesktopInternalOnly
    docker_compose_hidden_from_user = $runtimeHiddenFromOperator
    transport_security = "local_http_private_lan"
    public_external_beta_blockers = @(
        "unsigned_installer",
        "local_http_without_trusted_certificate",
        "manual_docker_desktop_runtime"
    )
    status_evidence_path = $StatusEvidenceJson
    status_evidence = $statusEvidence
    support_bundle_path = $SupportBundlePath
    support_bundle_sha256 = $supportBundleSha
}

$outputDir = Split-Path -Parent $OutputJson
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}
$evidence | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
Write-Host "Hub install evidence JSON: $OutputJson"
Write-Host "Hub install proof_result=$($evidence.proof_result)"
