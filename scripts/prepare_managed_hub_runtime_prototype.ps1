param(
    [string]$OutputJson = "",
    [string]$RuntimeExecutablePath = "",
    [string]$ComposeExecutablePath = "",
    [switch]$ConfirmManagedRuntimePrototype,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

if (-not $ConfirmManagedRuntimePrototype) {
    throw "Preparing the managed Hub runtime prototype requires -ConfirmManagedRuntimePrototype."
}

function Test-PrototypeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    try {
        & $Command @Arguments *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

$paths = Get-ImmoAppCanonicalRuntimePaths
$dirs = @(
    $paths.AppDataRoot,
    $paths.RuntimeRoot,
    $paths.ConfigRoot,
    $paths.DataRoot,
    $paths.LogsRoot
)

if (-not $ValidateOnly) {
    foreach ($dir in $dirs) {
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }
}

$runtimeExists = -not [string]::IsNullOrWhiteSpace($RuntimeExecutablePath) -and (Test-Path -LiteralPath $RuntimeExecutablePath -PathType Leaf)
$composeExists = -not [string]::IsNullOrWhiteSpace($ComposeExecutablePath) -and (Test-Path -LiteralPath $ComposeExecutablePath -PathType Leaf)
$runtimeUnderCanonicalRoot = $false
$composeUnderCanonicalRoot = $false
$runtimeCommandOk = $false
$composeCommandOk = $false

if ($runtimeExists) {
    $RuntimeExecutablePath = [System.IO.Path]::GetFullPath($RuntimeExecutablePath)
    $runtimeUnderCanonicalRoot = (
        (Test-ImmoAppPathUnderRoot -Root $paths.RuntimeRoot -Path $RuntimeExecutablePath) -and
        (Test-ImmoAppResolvedPathUnderRoot -Root $paths.RuntimeRoot -Path $RuntimeExecutablePath) -and
        -not (Test-ImmoAppPathHasReparsePoint -Path $RuntimeExecutablePath)
    )
    if ($runtimeUnderCanonicalRoot) {
        $runtimeCommandOk = Test-PrototypeCommand -Command $RuntimeExecutablePath -Arguments @("version")
    }
}

if ($composeExists) {
    $ComposeExecutablePath = [System.IO.Path]::GetFullPath($ComposeExecutablePath)
    $composeUnderCanonicalRoot = (
        (Test-ImmoAppPathUnderRoot -Root $paths.RuntimeRoot -Path $ComposeExecutablePath) -and
        (Test-ImmoAppResolvedPathUnderRoot -Root $paths.RuntimeRoot -Path $ComposeExecutablePath) -and
        -not (Test-ImmoAppPathHasReparsePoint -Path $ComposeExecutablePath)
    )
    if ($composeUnderCanonicalRoot) {
        $composeCommandOk = Test-PrototypeCommand -Command $ComposeExecutablePath -Arguments @("version")
    }
}
elseif ($runtimeCommandOk) {
    $composeCommandOk = Test-PrototypeCommand -Command $RuntimeExecutablePath -Arguments @("compose", "version")
}

$reasonCode = "managed_runtime_artifact_missing"
$proofResult = "NO-GO"
$agencyStatus = "NO_GO"
$internalStatus = "NO_GO"
$reason = "No hidden ImmoApp-managed runtime artifact was supplied. Prototype directories are prepared only."
$readyForPackageInventory = $false
$readyForProviderRegistration = $false
$missingProofTracks = @(
    "schema_v2_package_inventory",
    "vendor_runtime_provenance",
    "provider_registration",
    "provider_detection",
    "hub_startup_proof",
    "backup_restore_proof",
    "real_lan_workstation_proof"
)
$nextCommands = @(
    "Place or build a hidden managed runtime ZIP under C:\ProgramData\ImmoApp\runtime.",
    "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create_managed_runtime_vendor_provenance.ps1 -ArtifactPath <runtime.zip> -ExtractedRuntimeRoot <runtime-tree> -ArtifactKind zip -VendorName <vendor> -RuntimeName <runtime> -RuntimeVersion <version> -RuntimeLicense <license> -InternalSourceReference <reference> -ApprovalReason <reason> -LicenseDistributionAllowed `$true -LicenseReviewStatus approved -ApprovedBy <approver> -ApprovedByImmoApp",
    "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_managed_hub_runtime_package.ps1 -RuntimeSourceRoot <runtime-tree> -OutputRoot C:\ProgramData\ImmoApp\runtime\package -AllowExternalRuntimeSource -VendorProvenanceJson C:\ProgramData\ImmoApp\config\managed_runtime_vendor_provenance.json -RuntimeExecutableRelativePath <runtime.exe>",
    "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_managed_hub_runtime_provider.ps1 -RuntimeExecutablePath <runtime.exe> -InstallRoot C:\ProgramData\ImmoApp\runtime -DataRoot C:\ProgramData\ImmoApp\data -LogsRoot C:\ProgramData\ImmoApp\logs -PackageInventoryJson <inventory.json> -InstallerSha256 <installer-sha256> -ConfirmManagedRuntimeProof",
    "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\detect_hub_runtime.ps1",
    "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_hub_m1_local_proof.ps1 -StartHubForProof -BackupRestoreEvidenceJson <backup-restore-evidence.json>",
    "Run real workstation LAN proof from a second workstation or VM using the Hub IP/hostname."
)
if ($runtimeExists -and -not $runtimeUnderCanonicalRoot) {
    $reasonCode = "managed_runtime_outside_canonical_root"
    $reason = "Runtime executable exists but is not under the canonical ProgramData runtime root or uses a reparse point."
}
elseif ($runtimeExists -and -not $runtimeCommandOk) {
    $reasonCode = "managed_runtime_command_failed"
    $reason = "Runtime executable exists under ProgramData but did not pass the version check."
}
elseif ($runtimeCommandOk -and -not $composeCommandOk) {
    $reasonCode = "managed_runtime_compose_failed"
    $reason = "Runtime executable exists under ProgramData but no Compose-capable command passed validation."
}
elseif ($runtimeCommandOk -and $composeCommandOk) {
    $reasonCode = "managed_runtime_prototype_ready_for_provider_registration"
    $reason = "A ProgramData runtime and Compose-capable command passed prototype validation; provider registration and package provenance are still required."
    $internalStatus = "GO"
    $readyForPackageInventory = $true
    $readyForProviderRegistration = $false
    $missingProofTracks = @(
        "schema_v2_package_inventory",
        "vendor_runtime_provenance",
        "provider_registration",
        "provider_detection",
        "hub_startup_proof",
        "backup_restore_proof",
        "real_lan_workstation_proof"
    )
}

$result = [ordered]@{
    kind = "immoapp_managed_hub_runtime_prototype_scaffold"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    proof_result = $proofResult
    agency_install_status = $agencyStatus
    agency_ready = $false
    internal_proof_status = $internalStatus
    reason_code = $reasonCode
    reason = $reason
    validate_only = [bool]$ValidateOnly
    canonical_runtime_root = $paths.RuntimeRoot
    canonical_config_root = $paths.ConfigRoot
    canonical_data_root = $paths.DataRoot
    canonical_logs_root = $paths.LogsRoot
    directories_checked = @($dirs)
    runtime_executable_path = $RuntimeExecutablePath
    runtime_exists = [bool]$runtimeExists
    runtime_under_canonical_root = [bool]$runtimeUnderCanonicalRoot
    runtime_command_ok = [bool]$runtimeCommandOk
    compose_executable_path = $ComposeExecutablePath
    compose_exists = [bool]$composeExists
    compose_under_canonical_root = [bool]$composeUnderCanonicalRoot
    compose_command_ok = [bool]$composeCommandOk
    ready_for_package_inventory = [bool]$readyForPackageInventory
    ready_for_provider_registration = [bool]$readyForProviderRegistration
    missing_proof_tracks = @($missingProofTracks)
    missing_artifacts = @($missingProofTracks)
    next_commands = @($nextCommands)
    provider_written = $false
}

if ($OutputJson) {
    $parent = Split-Path -Parent $OutputJson
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
}

$result | ConvertTo-Json -Depth 8
