param(
    [string]$RuntimeDetectionJson = "",
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Get-ReadinessStatusFromInventory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedKind
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ status = "NO-GO"; path = $Path; reason_code = "evidence_missing" }
    }
    try {
        if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
            return [ordered]@{ status = "NO-GO"; path = $Path; reason_code = "evidence_reparse_point" }
        }
        $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        if ([string]$data.kind -ne $ExpectedKind) {
            return [ordered]@{ status = "NO-GO"; path = $Path; reason_code = "evidence_wrong_kind" }
        }
        return [ordered]@{
            status = if ([string]$data.proof_result -eq "GO") { "GO" } else { "NO-GO" }
            path = $Path
            reason_code = [string](Get-ImmoAppObjectValue -Data $data -Name "reason_code")
            sha256 = Get-ImmoAppFileSha256 -Path $Path
        }
    }
    catch {
        return [ordered]@{ status = "NO-GO"; path = $Path; reason_code = "evidence_invalid_json"; reason = $_.Exception.Message }
    }
}

$paths = Get-ImmoAppRuntimePaths
$config = $paths.ConfigRoot
$artifact = Get-ReadinessStatusFromInventory -Path (Join-Path $config "managed_wsl2_runtime_artifact_inventory.json") -ExpectedKind "immoapp_managed_wsl2_runtime_artifact_inventory"
$imageBundle = Get-ReadinessStatusFromInventory -Path (Join-Path $config "managed_wsl2_runtime_image_bundle_inventory.json") -ExpectedKind "immoapp_managed_wsl2_runtime_image_bundle_inventory"
$rootfs = Get-ReadinessStatusFromInventory -Path (Join-Path $config "managed_wsl2_runtime_rootfs_inventory.json") -ExpectedKind "immoapp_managed_wsl2_runtime_rootfs_inventory"

$providerPath = Get-ImmoAppHubRuntimeProviderConfigPath
$providerStatus = "NO-GO"
$providerReason = "provider_config_missing"
if (Test-Path -LiteralPath $providerPath -PathType Leaf) {
    try {
        $provider = Get-Content -LiteralPath $providerPath -Raw | ConvertFrom-Json
        if ([string](Get-ImmoAppObjectValue -Data $provider -Name "runtime_dependency_mode") -eq "managed_wsl2_container_runtime_artifact") {
            $providerStatus = "GO"
            $providerReason = "managed_wsl2_artifact_provider_registered"
        }
        else {
            $providerReason = "provider_not_managed_wsl2_artifact"
        }
    }
    catch {
        $providerReason = "provider_config_invalid"
    }
}

$distroStatus = "NO-GO"
$distroReason = "managed_wsl2_runtime_distribution_not_proven"
try {
    $wsl = Get-Command "wsl.exe" -ErrorAction Stop
    $list = & $wsl.Source -l -q 2>$null
    if ($LASTEXITCODE -eq 0 -and @($list | Where-Object { $_.Trim() -eq "ImmoAppRuntime" }).Count -gt 0) {
        $distroStatus = "GO"
        $distroReason = "managed_wsl2_runtime_distribution_present"
    }
}
catch {
    $distroReason = "wsl_unavailable"
}

$detection = $null
if ($RuntimeDetectionJson -and (Test-Path -LiteralPath $RuntimeDetectionJson -PathType Leaf)) {
    $detection = Get-Content -LiteralPath $RuntimeDetectionJson -Raw | ConvertFrom-Json
}
else {
    try {
        $detectJson = Join-Path $paths.LogsRoot "hub_runtime_readiness_detect_runtime.json"
        & (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") -OutputJson $detectJson | Out-Null
        if (Test-Path -LiteralPath $detectJson -PathType Leaf) {
            $detection = Get-Content -LiteralPath $detectJson -Raw | ConvertFrom-Json
        }
    }
    catch {
        $detection = $null
    }
}

$runtimeStartStatus = "NO-GO"
$frontDoorHealthStatus = "NO-GO"
$agencyStatus = "NO_GO"
if ($detection) {
    $runtimeStartStatus = [string](Get-ImmoAppObjectValue -Data $detection -Name "runtime_start_status")
    if ([string]::IsNullOrWhiteSpace($runtimeStartStatus)) { $runtimeStartStatus = "NO-GO" }
    $frontDoorHealthStatus = [string](Get-ImmoAppObjectValue -Data $detection -Name "front_door_health_status")
    if ([string]::IsNullOrWhiteSpace($frontDoorHealthStatus)) { $frontDoorHealthStatus = "NO-GO" }
    $agencyStatus = [string](Get-ImmoAppObjectValue -Data $detection -Name "agency_install_status")
    if ([string]::IsNullOrWhiteSpace($agencyStatus)) { $agencyStatus = "NO_GO" }
}

$summary = [ordered]@{
    kind = "immoapp_hub_runtime_readiness_summary"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    runtime_artifact_status = $artifact.status
    image_bundle_status = $imageBundle.status
    rootfs_status = $rootfs.status
    distro_import_status = $distroStatus
    provider_registration_status = $providerStatus
    runtime_start_status = if ($runtimeStartStatus -eq "GO") { "GO" } else { "NO-GO" }
    front_door_health_status = if ($frontDoorHealthStatus -eq "GO") { "GO" } else { "NO-GO" }
    lan_proof_status = "NO-GO"
    agency_install_status = $agencyStatus
    public_beta_status = "NO_GO"
    exact_next_command = "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hub_manager.ps1 -Action start -OutputJson C:\ProgramData\ImmoApp\logs\managed_wsl2_runtime_start_evidence.json"
    details = [ordered]@{
        artifact = $artifact
        image_bundle = $imageBundle
        rootfs = $rootfs
        distro_reason_code = $distroReason
        provider_reason_code = $providerReason
    }
}

if ($OutputJson) {
    $approvedRoots = @($paths.LogsRoot, $paths.ConfigRoot, (Join-Path (Get-ImmoAppRepoRoot) ".tmp"))
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $summary -ApprovedRoots $approvedRoots -Depth 8 | Out-Null
}
$summary | ConvertTo-Json -Depth 8
