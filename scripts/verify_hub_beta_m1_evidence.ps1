param(
    [Parameter(Mandatory = $true)][string]$HubInstallEvidenceJson,
    [Parameter(Mandatory = $true)][string]$HubStatusEvidenceJson,
    [Parameter(Mandatory = $true)][string]$WorkstationReachabilityJson,
    [Parameter(Mandatory = $true)][string]$WorkstationProductProofJson,
    [Parameter(Mandatory = $true)][string]$BackupRestoreProofJson,
    [Parameter(Mandatory = $true)][string]$SupportBundleManifestJson,
    [string]$SupportBundlePath = "",
    [Parameter(Mandatory = $true)][string]$InstalledInventoryJson,
    [Parameter(Mandatory = $true)][string]$InstallLifecycleEvidenceJson,
    [Parameter(Mandatory = $true)][string]$SourceCommitSha,
    [Parameter(Mandatory = $true)][string]$InstallerSha256,
    [Parameter(Mandatory = $true)][string]$OutputJson
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-LocalhostUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    try { $uri = [Uri]$Url } catch { return $false }
    return $uri.Host.Trim().ToLowerInvariant() -in @("localhost", "127.0.0.1", "::1")
}

function Read-Evidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$ExpectedKinds
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Evidence file not found or not a leaf file: $Path" }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) { throw "Evidence file path contains a reparse point, symlink, or junction: $Path" }
    try {
        $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        throw "Evidence file is not valid JSON: $Path $($_.Exception.Message)"
    }
    if (($ExpectedKinds -notcontains [string]$data.kind)) {
        throw "Evidence file has wrong kind. expected=$($ExpectedKinds -join ',') path=$Path"
    }
    if ([string]::IsNullOrWhiteSpace([string](Get-EvidenceValue -Data $data -Name "schema_version"))) {
        throw "Evidence file missing schema_version: $Path"
    }
    $proofResult = [string](Get-EvidenceValue -Data $data -Name "proof_result")
    $synthetic = [string](Get-EvidenceValue -Data $data -Name "synthetic")
    $isSynthetic = [string](Get-EvidenceValue -Data $data -Name "is_synthetic")
    $proofScope = ([string](Get-EvidenceValue -Data $data -Name "proof_scope")).ToLowerInvariant()
    if (
        $proofResult -eq "GO" -and
        (
            $synthetic -in @("true", "True", "1") -or
            $isSynthetic -in @("true", "True", "1") -or
            $proofScope -in @("synthetic", "local_only", "local_hub_only")
        )
    ) {
        throw "GO-bearing evidence cannot be synthetic or local-only: $Path"
    }
    return $data
}

function Get-EvidenceValue {
    param(
        [Parameter(Mandatory = $true)][object]$Data,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $property = $Data.PSObject.Properties[$Name]
    if ($null -eq $property) { return "" }
    return $property.Value
}

function Test-SyntheticEvidence {
    param([Parameter(Mandatory = $true)][object]$Data)
    $synthetic = [string](Get-EvidenceValue -Data $Data -Name "synthetic")
    $isSynthetic = [string](Get-EvidenceValue -Data $Data -Name "is_synthetic")
    $proofScope = ([string](Get-EvidenceValue -Data $Data -Name "proof_scope")).ToLowerInvariant()
    return (
        $synthetic -in @("true", "True", "1") -or
        $isSynthetic -in @("true", "True", "1") -or
        $proofScope -in @("synthetic", "local_only", "local_hub_only")
    )
}

function Test-StrictEvidenceIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Data,
        [Parameter(Mandatory = $true)][string]$Label
    )
    foreach ($field in @("schema_version", "created_at_utc", "machine_name", "source_commit_sha", "installer_sha256")) {
        if ([string]::IsNullOrWhiteSpace([string](Get-EvidenceValue -Data $Data -Name $field))) {
            return [ordered]@{ ok = $false; reason = "$Label evidence missing required identity field $field." }
        }
    }
    if ([string](Get-EvidenceValue -Data $Data -Name "proof_result") -ne "GO") {
        return [ordered]@{ ok = $false; reason = "$Label evidence must include proof_result=GO." }
    }
    if (Test-SyntheticEvidence -Data $Data) {
        return [ordered]@{ ok = $false; reason = "$Label evidence cannot be synthetic or local-only." }
    }
    $sourceCommit = [string](Get-EvidenceValue -Data $Data -Name "source_commit_sha")
    if ($sourceCommit -ne $SourceCommitSha) {
        return [ordered]@{ ok = $false; reason = "$Label evidence source_commit_sha does not match wrapper commit SHA." }
    }
    $installerHash = [string](Get-EvidenceValue -Data $Data -Name "installer_sha256")
    if ($installerHash.ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) {
        return [ordered]@{ ok = $false; reason = "$Label evidence installer_sha256 does not match wrapper installer hash." }
    }
    return [ordered]@{ ok = $true; reason = "" }
}

function Test-CanonicalProviderConfigPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    $canonical = if ((Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root") {
        [System.IO.Path]::GetFullPath((Get-ImmoAppHubRuntimeProviderConfigPath))
    } else {
        [System.IO.Path]::GetFullPath((Get-ImmoAppCanonicalHubRuntimeProviderConfigPath))
    }
    $actual = [System.IO.Path]::GetFullPath($Path)
    return $actual.Equals($canonical, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-LowerSha256 {
    param([string]$Value)
    return (-not [string]::IsNullOrWhiteSpace($Value) -and $Value -match "^[0-9a-f]{64}$")
}

function New-Phase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Ok,
        [string]$Reason = "",
        [object]$Artifact = $null
    )
    return [ordered]@{
        name = $Name
        status = if ($Ok) { "GO" } else { "NO-GO" }
        reason = $Reason
        artifact = $Artifact
    }
}

$phases = New-Object System.Collections.Generic.List[object]
$hubInstall = Read-Evidence -Path $HubInstallEvidenceJson -ExpectedKinds @("immoapp_hub_install_evidence")
$hubInstallIdentity = Test-StrictEvidenceIdentity -Data $hubInstall -Label "Hub install"
$hubInstallMode = [string](Get-ImmoAppObjectValue -Data $hubInstall -Name "install_mode")
if ([string]::IsNullOrWhiteSpace($hubInstallMode)) { $hubInstallMode = "desktop_and_hub" }
$hubInstallOk = (
    $hubInstallIdentity.ok -eq $true -and
    [string]$hubInstall.proof_result -eq "GO" -and
    [string]$hubInstall.source_commit_sha -eq $SourceCommitSha -and
    ([string]$hubInstall.installer_sha256).ToLowerInvariant() -eq $InstallerSha256.ToLowerInvariant() -and
    [string]$hubInstall.runtime_dependency_mode -eq "managed_container_runtime" -and
    [string]$hubInstall.agency_install_status -eq "GO" -and
    [string]$hubInstall.runtime_detection.provider_validation_status -eq "valid" -and
    [string]$hubInstall.runtime_detection.reason_code -eq "managed_runtime_ready" -and
    [string]$hubInstall.runtime_detection.runtime_dependency_mode -eq "managed_container_runtime" -and
    (Test-CanonicalProviderConfigPath -Path ([string]$hubInstall.runtime_detection.provider_config_path)) -and
    [string]$hubInstall.runtime_provider_proof.proof_only -ne "True" -and
    (Test-ImmoAppInstalledSource -Source ([string]$hubInstall.hub_manager_script_source)) -and
    ($hubInstallMode -eq "hub_only" -or (Test-ImmoAppInstalledSource -Source ([string]$hubInstall.desktop_exe_source))) -and
    -not (Test-SyntheticEvidence -Data $hubInstall) -and
    -not (Test-LocalhostUrl -Url ([string]$hubInstall.hub_base_url))
)
$phases.Add((New-Phase -Name "hub_install" -Ok $hubInstallOk -Reason $(if ($hubInstallOk) { "" } elseif ($hubInstallIdentity.ok -ne $true) { [string]$hubInstallIdentity.reason } else { "Hub install evidence is not real-agency GO." }) -Artifact $HubInstallEvidenceJson))

$hubStatus = Read-Evidence -Path $HubStatusEvidenceJson -ExpectedKinds @("immoapp_hub_status_evidence")
$hubStatusIdentity = Test-StrictEvidenceIdentity -Data $hubStatus -Label "Hub status"
$hubStatusOk = (
    $hubStatusIdentity.ok -eq $true -and
    [string]$hubStatus.proof_result -eq "GO" -and
    [string]$hubStatus.hub_status -eq "Online" -and
    -not (Test-LocalhostUrl -Url ([string]$hubStatus.hub_base_url)) -and
    [string]$hubStatus.database_health -eq "ok" -and
    [string]$hubStatus.storage_photos_health -eq "ok" -and
    [string]$hubStatus.worker_health -eq "ok" -and
    [string]$hubStatus.runtime_dependency_mode -eq "managed_container_runtime" -and
    [string]$hubStatus.agency_install_status -eq "GO" -and
    [string]$hubStatus.runtime_detection.provider_validation_status -eq "valid" -and
    [string]$hubStatus.runtime_detection.reason_code -eq "managed_runtime_ready" -and
    [string]$hubStatus.runtime_detection.runtime_dependency_mode -eq "managed_container_runtime" -and
    (Test-CanonicalProviderConfigPath -Path ([string]$hubStatus.runtime_detection.provider_config_path)) -and
    [string]$hubStatus.runtime_provider_proof.proof_only -ne "True" -and
    -not (Test-SyntheticEvidence -Data $hubStatus)
)
$phases.Add((New-Phase -Name "hub_status" -Ok $hubStatusOk -Reason $(if ($hubStatusOk) { "" } elseif ($hubStatusIdentity.ok -ne $true) { [string]$hubStatusIdentity.reason } else { "Hub status evidence is not fully online." }) -Artifact $HubStatusEvidenceJson))

$reachability = Read-Evidence -Path $WorkstationReachabilityJson -ExpectedKinds @("immoapp_lan_workstation_reachability_proof")
$reachabilityIdentity = Test-StrictEvidenceIdentity -Data $reachability -Label "Workstation reachability"
$reachabilityOk = ($reachabilityIdentity.ok -eq $true -and [int]$reachability.health_status -eq 200 -and -not (Test-LocalhostUrl -Url ([string]$reachability.hub_base_url)) -and -not (Test-SyntheticEvidence -Data $reachability))
$phases.Add((New-Phase -Name "workstation_reachability" -Ok $reachabilityOk -Reason $(if ($reachabilityOk) { "" } elseif ($reachabilityIdentity.ok -ne $true) { [string]$reachabilityIdentity.reason } else { "Workstation reachability must use Hub IP/hostname and health 200." }) -Artifact $WorkstationReachabilityJson))

$product = Read-Evidence -Path $WorkstationProductProofJson -ExpectedKinds @("immoapp_manual_product_proof_evidence")
$productIdentity = Test-StrictEvidenceIdentity -Data $product -Label "Workstation product proof"
$productOk = ($productIdentity.ok -eq $true -and $product.owner_login_proof -eq $true -and $product.create_read_update_proof -eq $true -and $product.offer_photo_thumbnail_proof -eq $true -and -not (Test-SyntheticEvidence -Data $product))
$phases.Add((New-Phase -Name "workstation_product_proof" -Ok $productOk -Reason $(if ($productOk) { "" } elseif ($productIdentity.ok -ne $true) { [string]$productIdentity.reason } else { "Workstation product proof is incomplete." }) -Artifact $WorkstationProductProofJson))

$backup = Read-Evidence -Path $BackupRestoreProofJson -ExpectedKinds @("immoapp_release_backup_restore_evidence", "immoapp_beta_release_backup_restore_evidence")
$backupIdentity = Test-StrictEvidenceIdentity -Data $backup -Label "Backup/restore"
$backupCheck = Test-ImmoAppStrictBackupRestoreEvidence -Path $BackupRestoreProofJson -ExpectedSourceCommitSha $SourceCommitSha -ExpectedInstallerSha256 $InstallerSha256
$backupOk = ($backupIdentity.ok -eq $true -and $backupCheck.ok -eq $true)
$phases.Add((New-Phase -Name "backup_restore" -Ok $backupOk -Reason $(if ($backupOk) { "" } elseif ($backupIdentity.ok -ne $true) { [string]$backupIdentity.reason } else { [string]$backupCheck.reason }) -Artifact $BackupRestoreProofJson))

$inventory = Read-Evidence -Path $InstalledInventoryJson -ExpectedKinds @("immoapp_installed_app_inventory", "immoapp_installed_inventory")
$inventoryIdentity = Test-StrictEvidenceIdentity -Data $inventory -Label "Installed inventory"
$inventorySchema = [string](Get-EvidenceValue -Data $inventory -Name "schema_version")
$inventoryProof = [string](Get-EvidenceValue -Data $inventory -Name "proof_result")
$inventorySourceOk = (
    [string](Get-EvidenceValue -Data $inventory -Name "source_commit_sha") -eq $SourceCommitSha -or
    [string](Get-EvidenceValue -Data $inventory -Name "expected_source_commit_sha") -eq $SourceCommitSha
)
$inventoryInstaller = [string](Get-EvidenceValue -Data $inventory -Name "installer_sha256")
if ([string]::IsNullOrWhiteSpace($inventoryInstaller)) {
    $inventoryInstaller = [string](Get-EvidenceValue -Data $inventory -Name "installer_sha256_claimed_by_operator")
}
$forbiddenPathCount = 0
$forbiddenRaw = Get-EvidenceValue -Data $inventory -Name "forbidden_path_count"
if (-not [string]::IsNullOrWhiteSpace([string]$forbiddenRaw)) {
    [void][int]::TryParse([string]$forbiddenRaw, [ref]$forbiddenPathCount)
}
else {
    $forbiddenPathCount = @((Get-EvidenceValue -Data $inventory -Name "forbidden_path_matches")).Count
}
$remoteInventory = ([string](Get-EvidenceValue -Data $inventory -Name "remote_evidence")).ToLowerInvariant() -in @("true", "1", "yes")
$inventoryInstallerVerified = ([string](Get-EvidenceValue -Data $inventory -Name "installer_sha256_verified")).ToLowerInvariant() -in @("true", "1", "yes")
$inventoryInstallerClaimedOnly = ([string](Get-EvidenceValue -Data $inventory -Name "installer_sha256_claimed_only")).ToLowerInvariant() -in @("true", "1", "yes")
$remoteInventoryHashOk = $true
if ($remoteInventory) {
    $remoteInventoryHashOk = (
        (Test-LowerSha256 -Value ([string](Get-EvidenceValue -Data $inventory -Name "evidence_file_sha256"))) -and
        (Test-LowerSha256 -Value ([string](Get-EvidenceValue -Data $inventory -Name "installed_inventory_sha256"))) -and
        (Test-LowerSha256 -Value ([string](Get-EvidenceValue -Data $inventory -Name "support_bundle_sha256")))
    )
}
$inventoryInstallerProofOk = if ($remoteInventory) { -not $inventoryInstallerClaimedOnly } else { ($inventoryInstallerVerified -and -not $inventoryInstallerClaimedOnly) }
$inventoryOk = (
    $inventoryIdentity.ok -eq $true -and
    -not [string]::IsNullOrWhiteSpace($inventorySchema) -and
    $inventoryProof -eq "GO" -and
    $inventorySourceOk -and
    $inventoryInstaller.ToLowerInvariant() -eq $InstallerSha256.ToLowerInvariant() -and
    -not [string]::IsNullOrWhiteSpace([string](Get-EvidenceValue -Data $inventory -Name "installed_exe_path")) -and
    (Test-LowerSha256 -Value ([string](Get-EvidenceValue -Data $inventory -Name "installed_exe_sha256"))) -and
    $forbiddenPathCount -eq 0 -and
    $inventoryInstallerProofOk -and
    $remoteInventoryHashOk
)
$phases.Add((New-Phase -Name "installed_inventory" -Ok $inventoryOk -Reason $(if ($inventoryOk) { "" } elseif ($inventoryIdentity.ok -ne $true) { [string]$inventoryIdentity.reason } else { "Installed inventory must be GO, match commit/installer hash, include installed exe path/SHA, have zero forbidden paths, reject claimed-only local installer hashes, and carry remote evidence/support hashes when remote." }) -Artifact $InstalledInventoryJson))

$lifecycle = Read-Evidence -Path $InstallLifecycleEvidenceJson -ExpectedKinds @("immoapp_install_lifecycle_evidence", "immoapp_install_uninstall_reinstall_lifecycle")
$lifecycleIdentity = Test-StrictEvidenceIdentity -Data $lifecycle -Label "Install lifecycle"
$lifecycleOk = ($lifecycleIdentity.ok -eq $true -and ([string](Get-EvidenceValue -Data $lifecycle -Name "lifecycle_status") -eq "GO" -or [string](Get-EvidenceValue -Data $lifecycle -Name "proof_result") -eq "GO"))
$phases.Add((New-Phase -Name "install_lifecycle" -Ok $lifecycleOk -Reason $(if ($lifecycleOk) { "" } elseif ($lifecycleIdentity.ok -ne $true) { [string]$lifecycleIdentity.reason } else { "Install lifecycle is not GO." }) -Artifact $InstallLifecycleEvidenceJson))

$supportManifest = Read-Evidence -Path $SupportBundleManifestJson -ExpectedKinds @("immoapp_support_bundle_manifest")
$supportIdentity = Test-StrictEvidenceIdentity -Data $supportManifest -Label "Support bundle manifest"
$supportManifestHash = [string](Get-EvidenceValue -Data $supportManifest -Name "bundle_sha256")
if ([string]::IsNullOrWhiteSpace($supportManifestHash)) {
    $supportManifestHash = [string](Get-EvidenceValue -Data $supportManifest -Name "support_bundle_sha256")
}
if ([string]::IsNullOrWhiteSpace($SupportBundlePath)) {
    $SupportBundlePath = [string](Get-EvidenceValue -Data $supportManifest -Name "bundle_path")
}
if ([string]::IsNullOrWhiteSpace($SupportBundlePath)) {
    $SupportBundlePath = [string](Get-EvidenceValue -Data $supportManifest -Name "support_bundle_path")
}
$supportBundleExists = -not [string]::IsNullOrWhiteSpace($SupportBundlePath) -and (Test-Path -LiteralPath $SupportBundlePath -PathType Leaf)
$supportBundlePathSafe = $supportBundleExists -and -not (Test-ImmoAppPathHasReparsePoint -Path $SupportBundlePath)
$supportBundleHash = if ($supportBundleExists) { Get-FileSha256 -Path $SupportBundlePath } else { $supportManifestHash }
$supportRemote = ([string](Get-EvidenceValue -Data $supportManifest -Name "remote_evidence")).ToLowerInvariant() -in @("true", "1", "yes")
$supportCopiedArtifactSha = [string](Get-EvidenceValue -Data $supportManifest -Name "copied_artifact_sha256")
$supportEvidenceFileSha = [string](Get-EvidenceValue -Data $supportManifest -Name "evidence_file_sha256")
$supportHashMatchesLocal = ($supportBundlePathSafe -and (Test-LowerSha256 -Value $supportManifestHash) -and $supportBundleHash -eq $supportManifestHash.ToLowerInvariant())
$supportRemoteHashOk = (
    $supportRemote -and
    (Test-LowerSha256 -Value $supportManifestHash) -and
    (Test-LowerSha256 -Value $supportCopiedArtifactSha) -and
    (Test-LowerSha256 -Value $supportEvidenceFileSha) -and
    $supportCopiedArtifactSha.ToLowerInvariant() -eq $supportManifestHash.ToLowerInvariant()
)
$supportOk = (
    $supportIdentity.ok -eq $true -and
    [string](Get-EvidenceValue -Data $supportManifest -Name "proof_result") -eq "GO" -and
    ($supportHashMatchesLocal -or $supportRemoteHashOk)
)
$supportFailureReason = if ($supportOk) {
    ""
} elseif ($supportIdentity.ok -ne $true) {
    [string]$supportIdentity.reason
} elseif ($supportRemote -and (Test-LowerSha256 -Value $supportManifestHash) -and (Test-LowerSha256 -Value $supportCopiedArtifactSha) -and $supportCopiedArtifactSha.ToLowerInvariant() -ne $supportManifestHash.ToLowerInvariant()) {
    "Support bundle remote copied_artifact_sha256 must match bundle_sha256/support_bundle_sha256."
} else {
    "Support bundle proof must be local path plus matching hash or remote_evidence=true plus copied artifact hash."
}
$supportArtifact = [ordered]@{
    manifest = $SupportBundleManifestJson
    bundle_path = $SupportBundlePath
    bundle_exists = $supportBundleExists
    bundle_sha256 = $supportBundleHash
    copied_artifact_sha256 = $supportCopiedArtifactSha
    evidence_file_sha256 = $supportEvidenceFileSha
}
$phases.Add((New-Phase -Name "support_bundle" -Ok $supportOk -Reason $supportFailureReason -Artifact $supportArtifact))

$failed = @($phases | Where-Object { $_.status -ne "GO" })
$evidence = [ordered]@{
    kind = "immoapp_hub_beta_m1_go_no_go_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    source_commit_sha = $SourceCommitSha
    installer_sha256 = $InstallerSha256.ToLowerInvariant()
    installed_version = [string]$hubInstall.installed_version
    installed_build_identity = $hubInstall.installed_build_identity
    proof_result = if ($failed.Count -eq 0) { "GO" } else { "NO-GO" }
    failure_reason = if ($failed.Count -eq 0) { "" } else { (($failed | ForEach-Object { "$($_.name): $($_.reason)" }) -join " ") }
    phases = @($phases.ToArray())
    support_bundle_manifest_json = (Resolve-Path -LiteralPath $SupportBundleManifestJson).Path
    support_bundle_path = if ($supportBundleExists) { (Resolve-Path -LiteralPath $SupportBundlePath).Path } else { $SupportBundlePath }
    support_bundle_sha256 = $supportBundleHash
}

$outputDir = Split-Path -Parent $OutputJson
$approvedOutputRoot = if ($outputDir) { $outputDir } else { (Get-Location).Path }
Write-ImmoAppSafeJson -Path $OutputJson -Payload $evidence -ApprovedRoots @($approvedOutputRoot) -Depth 12 | Out-Null
Write-Host "Hub Beta M1 evidence JSON: $OutputJson"
Write-Host "Hub Beta M1 proof_result=$($evidence.proof_result)"
if ($failed.Count -gt 0) {
    exit 1
}
