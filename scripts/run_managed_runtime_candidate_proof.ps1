param(
    [string]$RuntimeZipArtifact = "",
    [string]$ExtractedRuntimeRoot = "",
    [string]$VendorName = "",
    [string]$RuntimeName = "",
    [string]$RuntimeVersion = "",
    [string]$RuntimeLicense = "",
    [string]$RuntimeSourceUrl = "",
    [string]$InternalSourceReference = "",
    [string]$VendorProvenanceJson = "",
    [string]$ApprovalReason = "",
    [string]$ApprovedBy = "",
    [string]$ApprovedAtUtc = "",
    [string]$LicenseReviewStatus = "",
    [string]$SourceCommitSha = "",
    [string]$InstallerSha256 = "",
    [string]$RuntimeExecutableRelativePath = "",
    [string]$ComposeExecutableRelativePath = "",
    [string]$BackupRestoreEvidenceJson = "",
    [string]$OutputJson = "",
    [switch]$ConfirmManagedRuntimeCandidateProof,
    [switch]$ConfirmLicenseDistributionApproved,
    [switch]$StartHubForProof,
    [switch]$PromoteCandidateProvider,
    [switch]$ConfirmPromoteManagedRuntime
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

if (-not $ConfirmManagedRuntimeCandidateProof) {
    throw "Managed runtime candidate proof requires -ConfirmManagedRuntimeCandidateProof."
}

function New-CandidatePhase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$ReasonCode = "",
        [string]$Reason = "",
        [object]$Artifact = $null
    )
    return [ordered]@{
        name = $Name
        status = $Status
        reason_code = $ReasonCode
        reason = $Reason
        artifact = $Artifact
    }
}

function Add-Missing {
    param([string]$Name)
    if (-not [string]::IsNullOrWhiteSpace($Name) -and -not $missing.Contains($Name)) {
        [void]$missing.Add($Name)
    }
}

function Get-ProviderSnapshot {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = Assert-ImmoAppProviderSnapshotPathSafe -Path $Path -AllowNonCanonical
    $exists = Test-Path -LiteralPath $full -PathType Leaf
    return [ordered]@{
        path = $full
        existed = $exists
        sha256 = if ($exists) { Get-ImmoAppFileSha256 -Path $full } else { "" }
        content_base64 = if ($exists) { [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($full)) } else { "" }
    }
}

function Restore-ProviderSnapshot {
    param([Parameter(Mandatory = $true)]$Snapshot)
    $path = Assert-ImmoAppProviderSnapshotPathSafe -Path ([string]$Snapshot.path) -AllowNonCanonical
    $parent = Split-Path -Parent $path
    if ($Snapshot.existed -eq $true) {
        if ($parent -and -not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        if ($parent -and (Test-ImmoAppPathHasReparsePoint -Path $parent)) {
            throw "provider_restore_reparse_point|Provider restore parent contains a reparse point."
        }
        $temp = Join-Path $parent ([System.IO.Path]::GetFileName($path) + ".restore." + [System.Guid]::NewGuid().ToString("N"))
        try {
            [System.IO.File]::WriteAllBytes($temp, [Convert]::FromBase64String([string]$Snapshot.content_base64))
            if (Test-ImmoAppPathHasReparsePoint -Path $temp) {
                throw "provider_restore_temp_reparse_point|Provider restore temp file contains a reparse point."
            }
            Move-Item -LiteralPath $temp -Destination $path -Force
        }
        finally {
            if (Test-Path -LiteralPath $temp) {
                Remove-Item -LiteralPath $temp -Force
            }
        }
        $restoredSha = Get-ImmoAppFileSha256 -Path $path
        if ($restoredSha -ne [string]$Snapshot.sha256) {
            throw "provider_restore_hash_mismatch|Restored provider config SHA-256 does not match snapshot."
        }
    }
    elseif (Test-Path -LiteralPath $path) {
        if (Test-ImmoAppPathHasReparsePoint -Path $path) {
            throw "provider_restore_reparse_point|Refusing to remove provider config reparse point during restore."
        }
        Remove-Item -LiteralPath $path -Force
    }
    return $true
}

function Get-ProviderFinalStateSummary {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Snapshot,
        [string]$CandidateSha256 = "",
        [bool]$ProviderPromoted = $false,
        [bool]$ProviderRestored = $false
    )
    $safePath = Assert-ImmoAppProviderSnapshotPathSafe -Path $Path -AllowNonCanonical
    $sha = ""
    $state = "invalid"
    $active = $false
    if (Test-Path -LiteralPath $safePath -PathType Leaf) {
        $sha = Get-ImmoAppFileSha256 -Path $safePath
        if ($ProviderPromoted -and -not [string]::IsNullOrWhiteSpace($CandidateSha256) -and $sha -eq $CandidateSha256) {
            $state = "promoted"
            $active = $true
        }
        elseif ($ProviderRestored -and [bool]$Snapshot.existed -and $sha -eq [string]$Snapshot.sha256) {
            $state = "restored"
        }
        else {
            $state = "invalid"
        }
    }
    elseif ($ProviderRestored -and -not [bool]$Snapshot.existed) {
        $state = "missing"
    }
    return [ordered]@{
        sha256 = $sha
        state = $state
        active = $active
    }
}

function Test-ExplicitInlineLicenseApproval {
    return (
        $ConfirmLicenseDistributionApproved -and
        $LicenseReviewStatus -eq "approved" -and
        -not [string]::IsNullOrWhiteSpace($ApprovedBy) -and
        -not [string]::IsNullOrWhiteSpace($ApprovalReason)
    )
}

$paths = Ensure-ImmoAppRuntimeLayout
$phases = New-Object System.Collections.Generic.List[object]
$missing = New-Object System.Collections.Generic.List[string]
$candidateProofRunId = [System.Guid]::NewGuid().ToString("N")
$candidateRoot = Join-Path (Join-Path $paths.RuntimeRoot "candidate-proof") $candidateProofRunId
$generatedProvenanceJson = Join-Path $candidateRoot "vendor_provenance.inline.json"
$packageOutputRoot = Join-Path $candidateRoot "package"
$providerPath = Get-ImmoAppHubRuntimeProviderConfigPath
$providerLock = $null
$providerLockStatus = "not_acquired"
$providerLockReleased = $false
$providerSnapshot = [ordered]@{
    path = $providerPath
    existed = $false
    sha256 = ""
    content_base64 = ""
}
$providerRestored = $false
$providerPromoted = $false
$providerConfigSha256Final = ""
$providerFinalState = "unknown"
$providerActiveAfterProof = $false
$providerPromotionStatus = "not_requested"
$candidateProviderSha256 = ""
$providerRestoreFailed = $false
$promotionFinalConfirmed = $false
$finalPromotionDetection = $null
$provenanceSource = "missing"
$effectiveProvenanceJson = ""

try {
    $providerLock = Enter-ImmoAppProviderMutationLock -TimeoutSeconds 60
    $providerLockStatus = "acquired"
    $providerSnapshot = Get-ProviderSnapshot -Path $providerPath
    $phases.Add((New-CandidatePhase -Name "provider_lock" -Status "GO" -ReasonCode "provider_lock_acquired" -Artifact ([string]$providerLock.path)))
}
catch {
    $providerLockStatus = "NO-GO"
    $phases.Add((New-CandidatePhase -Name "provider_lock" -Status "NO-GO" -ReasonCode "provider_lock_timeout" -Reason $_.Exception.Message -Artifact (Get-ImmoAppProviderMutationLockPath)))
}

if ([string]::IsNullOrWhiteSpace($RuntimeZipArtifact)) {
    Add-Missing "runtime_zip_candidate"
}
else {
    if ([string]::IsNullOrWhiteSpace($ExtractedRuntimeRoot)) { Add-Missing "extracted_runtime_root" }
    if ([string]::IsNullOrWhiteSpace($SourceCommitSha)) { Add-Missing "source_commit_sha" }
    if ([string]::IsNullOrWhiteSpace($InstallerSha256)) { Add-Missing "installer_sha256" }
    if ([string]::IsNullOrWhiteSpace($RuntimeExecutableRelativePath)) { Add-Missing "runtime_executable_relative_path" }
}

try {
    if ($missing.Count -gt 0) {
        $phases.Add((New-CandidatePhase -Name "artifact_inputs" -Status "NO-GO" -ReasonCode "managed_runtime_candidate_missing_artifacts" -Reason "Managed runtime candidate proof is missing required artifact/provenance inputs." -Artifact @($missing.ToArray())))
    }
    else {
        $phases.Add((New-CandidatePhase -Name "artifact_inputs" -Status "GO" -Reason "Required candidate inputs are present."))
    }

    $provenanceOk = $false
    if ($missing.Count -eq 0) {
        if (-not [string]::IsNullOrWhiteSpace($VendorProvenanceJson)) {
            $effectiveProvenanceJson = $VendorProvenanceJson
            $provenanceSource = "vendor_provenance_json"
            try {
                $provenanceResult = Assert-ImmoAppManagedRuntimeVendorProvenance -ProvenancePath $effectiveProvenanceJson -ExpectedSourceCommitSha $SourceCommitSha
                if ($PromoteCandidateProvider -and [bool]$provenanceResult.manifest.proof_only) {
                    throw "vendor_provenance_proof_only|Promotion requires a non-proof vendor provenance manifest."
                }
                $provenanceOk = $true
                $phases.Add((New-CandidatePhase -Name "vendor_provenance" -Status "GO" -ReasonCode "vendor_provenance_verified" -Artifact $effectiveProvenanceJson))
            }
            catch {
                $phases.Add((New-CandidatePhase -Name "vendor_provenance" -Status "NO-GO" -ReasonCode "vendor_provenance_invalid" -Reason $_.Exception.Message -Artifact $effectiveProvenanceJson))
            }
        }
        elseif ($PromoteCandidateProvider) {
            $phases.Add((New-CandidatePhase -Name "vendor_provenance" -Status "NO-GO" -ReasonCode "vendor_provenance_required_for_promotion" -Reason "Promotion requires a separately generated -VendorProvenanceJson."))
        }
        elseif (Test-ExplicitInlineLicenseApproval) {
            $provenanceSource = "inline_explicit_approval"
            $effectiveProvenanceJson = $generatedProvenanceJson
            try {
                foreach ($field in @(
                    @{ name = "vendor_name"; value = $VendorName },
                    @{ name = "runtime_name"; value = $RuntimeName },
                    @{ name = "runtime_version"; value = $RuntimeVersion },
                    @{ name = "runtime_license"; value = $RuntimeLicense }
                )) {
                    if ([string]::IsNullOrWhiteSpace([string]$field.value)) {
                        throw "vendor_provenance_missing_field|Inline provenance approval requires $($field.name)."
                    }
                }
                $provenanceArgs = @{
                    ArtifactPath = $RuntimeZipArtifact
                    ArtifactKind = "zip"
                    ExtractedRuntimeRoot = $ExtractedRuntimeRoot
                    VendorName = $VendorName
                    RuntimeName = $RuntimeName
                    RuntimeVersion = $RuntimeVersion
                    RuntimeLicense = $RuntimeLicense
                    ApprovalReason = $ApprovalReason
                    SourceCommitSha = $SourceCommitSha
                    OutputJson = $effectiveProvenanceJson
                    ApprovedByImmoApp = $true
                    LicenseDistributionAllowed = "true"
                    LicenseReviewStatus = $LicenseReviewStatus
                    ApprovedBy = $ApprovedBy
                    ProofOnly = $true
                }
                if ($RuntimeSourceUrl) { $provenanceArgs.RuntimeSourceUrl = $RuntimeSourceUrl }
                if ($InternalSourceReference) { $provenanceArgs.InternalSourceReference = $InternalSourceReference }
                if ($ApprovedAtUtc) { $provenanceArgs.ApprovedAtUtc = $ApprovedAtUtc }
                & (Join-Path $PSScriptRoot "create_managed_runtime_vendor_provenance.ps1") @provenanceArgs *> $null
                $provenanceOk = $true
                $phases.Add((New-CandidatePhase -Name "vendor_provenance" -Status "GO" -ReasonCode "inline_explicit_license_approval_recorded" -Artifact $effectiveProvenanceJson))
            }
            catch {
                $phases.Add((New-CandidatePhase -Name "vendor_provenance" -Status "NO-GO" -ReasonCode "vendor_provenance_failed" -Reason $_.Exception.Message -Artifact $effectiveProvenanceJson))
            }
        }
        else {
            $phases.Add((New-CandidatePhase -Name "vendor_provenance" -Status "NO-GO" -ReasonCode "license_approval_missing" -Reason "Candidate proof requires -VendorProvenanceJson or explicit -ConfirmLicenseDistributionApproved -LicenseReviewStatus approved -ApprovedBy -ApprovalReason."))
        }
    }

    $packageInventoryPath = ""
    $packageOk = $false
    if ($provenanceOk) {
        try {
            $packageArgs = @{
                RuntimeSourceRoot = $ExtractedRuntimeRoot
                OutputRoot = $packageOutputRoot
                RuntimeExecutableRelativePath = $RuntimeExecutableRelativePath
                AllowExternalRuntimeSource = $true
                VendorProvenanceJson = $effectiveProvenanceJson
                AllowReplaceOutputRoot = $true
            }
            if ($ComposeExecutableRelativePath) { $packageArgs.ComposeExecutableRelativePath = $ComposeExecutableRelativePath }
            & (Join-Path $PSScriptRoot "build_managed_hub_runtime_package.ps1") @packageArgs | Out-Null
            $candidateInventory = Get-ChildItem -LiteralPath $packageOutputRoot -Filter "*inventory*.json" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
            if ($candidateInventory) {
                $packageInventoryPath = $candidateInventory.FullName
                $inventory = Get-Content -LiteralPath $packageInventoryPath -Raw | ConvertFrom-Json
                if ([string]$inventory.proof_result -eq "GO") {
                    $packageOk = $true
                    $phases.Add((New-CandidatePhase -Name "package_inventory" -Status "GO" -Artifact $packageInventoryPath))
                }
                else {
                    $phases.Add((New-CandidatePhase -Name "package_inventory" -Status "NO-GO" -ReasonCode ([string]$inventory.reason_code) -Reason "Package inventory did not reach GO." -Artifact $packageInventoryPath))
                }
            }
            else {
                $phases.Add((New-CandidatePhase -Name "package_inventory" -Status "NO-GO" -ReasonCode "managed_runtime_package_inventory_missing" -Reason "Package builder did not emit an inventory JSON."))
            }
        }
        catch {
            $phases.Add((New-CandidatePhase -Name "package_inventory" -Status "NO-GO" -ReasonCode "managed_runtime_package_build_failed" -Reason $_.Exception.Message))
        }
    }

    $registrationOk = $false
    if ($packageOk) {
        if ($providerLockStatus -ne "acquired") {
            $phases.Add((New-CandidatePhase -Name "provider_registration" -Status "NO-GO" -ReasonCode "provider_lock_not_acquired" -Reason "Provider registration requires the provider mutation lock."))
        }
        else {
        try {
            $runtimeExecutable = Join-Path $ExtractedRuntimeRoot $RuntimeExecutableRelativePath
            $composeExecutable = if ($ComposeExecutableRelativePath) { Join-Path $ExtractedRuntimeRoot $ComposeExecutableRelativePath } else { "" }
            $registerArgs = @{
                RuntimeExecutablePath = $runtimeExecutable
                InstallRoot = $ExtractedRuntimeRoot
                DataRoot = $paths.DataRoot
                LogsRoot = $paths.LogsRoot
                PackageInventoryJson = $packageInventoryPath
                SourceCommitSha = $SourceCommitSha
                InstallerSha256 = $InstallerSha256
                ProviderLock = $providerLock
                WriteProvider = $true
                ConfirmManagedRuntimeProof = $true
            }
            if ($composeExecutable) { $registerArgs.ComposeExecutablePath = $composeExecutable }
            if (-not (Test-ImmoAppUsingCanonicalRuntimeRoot)) {
                $registerArgs.AllowTestOnlyPath = $true
                [void]$registerArgs.Remove("PackageInventoryJson")
            }
            $registration = Invoke-ImmoAppManagedRuntimeProviderRegistration @registerArgs
            $registrationOk = ([string]$registration.provider_write_status -eq "GO")
            $candidateProviderSha256 = [string]$registration.provider_config_sha256_after_write
            $phases.Add((New-CandidatePhase -Name "provider_registration" -Status $(if ($registrationOk) { "GO" } else { "NO-GO" }) -ReasonCode ([string]$registration.reason_code) -Artifact $registration.provider_config_path))
            if ($registrationOk -and $env:IMMOAPP_TEST_CANDIDATE_FAIL_AFTER_PROVIDER_REGISTRATION -in @("1", "true", "yes", "on")) {
                throw "injected_failure_after_provider_registration|Injected candidate proof failure after provider registration."
            }
        }
        catch {
            $phases.Add((New-CandidatePhase -Name "provider_registration" -Status "NO-GO" -ReasonCode "provider_registration_failed" -Reason $_.Exception.Message))
        }
        }
    }

    $detectionOk = $false
    if ($registrationOk) {
        try {
            $detection = & (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") | ConvertFrom-Json
            $detectionOk = ([string]$detection.runtime_dependency_mode -eq "managed_container_runtime" -and [string]$detection.agency_install_status -eq "GO")
            $phases.Add((New-CandidatePhase -Name "runtime_detection" -Status $(if ($detectionOk) { "GO" } else { "NO-GO" }) -ReasonCode ([string]$detection.reason_code) -Artifact $detection.provider_config_path))
        }
        catch {
            $phases.Add((New-CandidatePhase -Name "runtime_detection" -Status "NO-GO" -ReasonCode "runtime_detection_failed" -Reason $_.Exception.Message))
        }
    }

    $hubStartupOk = $false
    $statusEvidencePath = Join-Path $candidateRoot "hub_status_evidence.json"
    $setupEvidencePath = Join-Path $candidateRoot "hub_setup_evidence.json"
    if ($detectionOk -and $StartHubForProof) {
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup_office_hub.ps1") -Role HubDesktop -OutputJson $setupEvidencePath | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "setup_office_hub.ps1 failed." }
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "collect_hub_status_evidence.ps1") -OutputJson $statusEvidencePath | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "collect_hub_status_evidence.ps1 failed." }
            $statusEvidence = Get-Content -LiteralPath $statusEvidencePath -Raw | ConvertFrom-Json
            $hubStartupOk = (
                [string]$statusEvidence.proof_result -eq "GO" -and
                [string]$statusEvidence.hub_status -eq "Online" -and
                [string]$statusEvidence.api_health -eq "ok"
            )
            $phases.Add((New-CandidatePhase -Name "hub_startup" -Status $(if ($hubStartupOk) { "GO" } else { "NO-GO" }) -ReasonCode ([string]$statusEvidence.status_reason_code) -Reason ([string]$statusEvidence.failure_reason) -Artifact $statusEvidencePath))
        }
        catch {
            $phases.Add((New-CandidatePhase -Name "hub_startup" -Status "NO-GO" -ReasonCode "stack_start_failed" -Reason $_.Exception.Message -Artifact $statusEvidencePath))
        }
    }
    elseif ($detectionOk) {
        $phases.Add((New-CandidatePhase -Name "hub_startup" -Status "NO-GO" -ReasonCode "start_hub_for_proof_not_requested" -Reason "Pass -StartHubForProof after a managed provider is registered."))
    }
    else {
        $phases.Add((New-CandidatePhase -Name "hub_startup" -Status "NO-GO" -ReasonCode "runtime_detection_not_go" -Reason "Runtime detection must be GO before Hub startup proof."))
    }

    $networkBoundaryOk = $false
    $networkEvidencePath = Join-Path $candidateRoot "network_boundary_evidence.json"
    if ($hubStartupOk) {
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_hub_network_boundary.ps1") -OutputJson $networkEvidencePath | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "verify_hub_network_boundary.ps1 failed." }
            $networkEvidence = Get-Content -LiteralPath $networkEvidencePath -Raw | ConvertFrom-Json
            $networkBoundaryOk = ([string]$networkEvidence.boundary_result -eq "GO")
            $phases.Add((New-CandidatePhase -Name "network_boundary" -Status $(if ($networkBoundaryOk) { "GO" } else { "NO-GO" }) -ReasonCode ([string]$networkEvidence.reason_code) -Artifact $networkEvidencePath))
        }
        catch {
            $phases.Add((New-CandidatePhase -Name "network_boundary" -Status "NO-GO" -ReasonCode "network_boundary_failed" -Reason $_.Exception.Message -Artifact $networkEvidencePath))
        }
    }
    else {
        $phases.Add((New-CandidatePhase -Name "network_boundary" -Status "NO-GO" -ReasonCode "hub_startup_not_go" -Reason "Network boundary proof requires Hub startup GO."))
    }

    if ([string]::IsNullOrWhiteSpace($BackupRestoreEvidenceJson)) {
        $phases.Add((New-CandidatePhase -Name "backup_restore" -Status "NO-GO" -ReasonCode "missing_restore_evidence" -Reason "Backup/restore evidence is required before agency readiness."))
    }
    else {
        try {
            $backupArgs = @{
                Path = $BackupRestoreEvidenceJson
                ExpectedSourceCommitSha = $SourceCommitSha
                ExpectedInstallerSha256 = $InstallerSha256
                ExpectedCandidateProofRunId = $candidateProofRunId
                ExpectedRuntimeDependencyMode = "managed_container_runtime"
                ExpectedProviderConfigPath = $providerPath
                ExpectedHubRuntimeProviderMode = "managed_container_runtime"
            }
            if (-not [string]::IsNullOrWhiteSpace($candidateProviderSha256)) {
                $backupArgs.ExpectedProviderConfigSha256 = $candidateProviderSha256
            }
            $backupCheck = Assert-ImmoAppStrictBackupRestoreEvidence @backupArgs
            $phases.Add((New-CandidatePhase -Name "backup_restore" -Status "GO" -ReasonCode ([string]$backupCheck.reason_code) -Artifact $BackupRestoreEvidenceJson))
            if (-not $PromoteCandidateProvider) {
                $phases.Add((New-CandidatePhase -Name "backup_restore_binding" -Status "GO" -ReasonCode "backup_restore_bound_to_candidate" -Reason "Backup/restore evidence matched the candidate proof run, runtime mode, provider path, and provider SHA."))
            }
        }
        catch {
            $parts = ([string]$_.Exception.Message).Split("|", 2)
            $reasonCode = if ($parts.Count -gt 1) { $parts[0] } else { "backup_restore_evidence_invalid" }
            $reason = if ($parts.Count -gt 1) { $parts[1] } else { $_.Exception.Message }
            $phases.Add((New-CandidatePhase -Name "backup_restore" -Status "NO-GO" -ReasonCode $reasonCode -Reason $reason -Artifact $BackupRestoreEvidenceJson))
        }
    }

    $supportBundleOk = $false
    $supportManifestPath = Join-Path $candidateRoot "support_bundle_manifest.json"
    if ($hubStartupOk) {
        try {
            $supportOutput = Join-Path $candidateRoot "support"
            New-Item -ItemType Directory -Path $supportOutput -Force | Out-Null
            $supportText = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "collect_desktop_support_bundle.ps1") -OutputDir $supportOutput
            if ($LASTEXITCODE -ne 0) { throw "collect_desktop_support_bundle.ps1 failed." }
            $supportBundlePath = (($supportText | Select-Object -Last 1 | Out-String).Trim())
            $supportSha = if ($supportBundlePath -and (Test-Path -LiteralPath $supportBundlePath)) { Get-ImmoAppFileSha256 -Path $supportBundlePath } else { "" }
            $supportBundleOk = ($supportSha -match "^[0-9a-f]{64}$")
            $supportPayload = [ordered]@{
                kind = "immoapp_support_bundle_manifest"
                schema_version = 1
                created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
                proof_result = if ($supportBundleOk) { "GO" } else { "NO-GO" }
                bundle_path = $supportBundlePath
                bundle_sha256 = $supportSha
            }
            Write-ImmoAppSafeJson -Path $supportManifestPath -Payload $supportPayload -ApprovedRoots @($paths.LogsRoot, $paths.RuntimeRoot) -Depth 8 | Out-Null
            $phases.Add((New-CandidatePhase -Name "support_bundle" -Status $(if ($supportBundleOk) { "GO" } else { "NO-GO" }) -ReasonCode $(if ($supportBundleOk) { "support_bundle_collected" } else { "support_bundle_missing_hash" }) -Artifact $supportManifestPath))
        }
        catch {
            $phases.Add((New-CandidatePhase -Name "support_bundle" -Status "NO-GO" -ReasonCode "support_bundle_failed" -Reason $_.Exception.Message -Artifact $supportManifestPath))
        }
    }
    else {
        $phases.Add((New-CandidatePhase -Name "support_bundle" -Status "NO-GO" -ReasonCode "hub_startup_not_go" -Reason "Support bundle proof requires Hub startup GO."))
    }
}
catch {
    $phases.Add((New-CandidatePhase -Name "candidate_proof_unhandled_failure" -Status "NO-GO" -ReasonCode "candidate_proof_unhandled_failure" -Reason $_.Exception.Message))
}
finally {
    $requiredForPromotion = @("artifact_inputs", "vendor_provenance", "package_inventory", "provider_registration", "runtime_detection", "hub_startup", "network_boundary", "backup_restore", "support_bundle")
    $candidateValidationOkForFinally = $true
    foreach ($phaseName in $requiredForPromotion) {
        if (@($phases | Where-Object { $_.name -eq $phaseName -and $_.status -eq "GO" }).Count -lt 1) {
            $candidateValidationOkForFinally = $false
            break
        }
    }
    if ($PromoteCandidateProvider) {
        $providerPromotionStatus = "NO-GO"
        if (-not $ConfirmPromoteManagedRuntime) {
            $phases.Add((New-CandidatePhase -Name "provider_restore_or_promotion" -Status "NO-GO" -ReasonCode "confirm_promote_managed_runtime_required" -Reason "Promotion requires -ConfirmPromoteManagedRuntime."))
        }
        elseif (-not $candidateValidationOkForFinally) {
            $phases.Add((New-CandidatePhase -Name "provider_restore_or_promotion" -Status "NO-GO" -ReasonCode "candidate_not_ready_for_promotion" -Reason "Promotion requires all managed runtime, Hub startup, network, backup/restore, and support phases to be GO."))
        }
        elseif ([string]::IsNullOrWhiteSpace($candidateProviderSha256)) {
            $phases.Add((New-CandidatePhase -Name "provider_restore_or_promotion" -Status "NO-GO" -ReasonCode "candidate_provider_sha_missing" -Reason "Provider promotion requires the candidate provider SHA-256 from registration."))
        }
        else {
            $providerPromoted = $true
            $state = Get-ProviderFinalStateSummary -Path $providerPath -Snapshot $providerSnapshot -CandidateSha256 $candidateProviderSha256 -ProviderPromoted $true -ProviderRestored $false
            if ([string]$state.state -eq "promoted" -and [bool]$state.active) {
                try {
                    $finalPromotionDetection = & (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") | ConvertFrom-Json
                    if (
                        [string]$finalPromotionDetection.runtime_dependency_mode -eq "managed_container_runtime" -and
                        [string]$finalPromotionDetection.agency_install_status -eq "GO"
                    ) {
                        $providerPromotionStatus = "GO"
                        $promotionFinalConfirmed = $true
                        $phases.Add((New-CandidatePhase -Name "provider_final_detection" -Status "GO" -ReasonCode ([string]$finalPromotionDetection.reason_code) -Artifact $finalPromotionDetection.provider_config_path))
                        $phases.Add((New-CandidatePhase -Name "provider_restore_or_promotion" -Status "GO" -ReasonCode "candidate_provider_promoted" -Reason "Candidate provider promotion was explicitly confirmed and final runtime detection is agency GO."))
                    }
                    else {
                        $phases.Add((New-CandidatePhase -Name "provider_final_detection" -Status "NO-GO" -ReasonCode ([string]$finalPromotionDetection.reason_code) -Reason "Final runtime detection did not confirm agency-ready managed provider." -Artifact $finalPromotionDetection.provider_config_path))
                    }
                }
                catch {
                    $phases.Add((New-CandidatePhase -Name "provider_final_detection" -Status "NO-GO" -ReasonCode "provider_final_detection_failed" -Reason $_.Exception.Message))
                }
            }
            else {
                $phases.Add((New-CandidatePhase -Name "provider_final_state" -Status "NO-GO" -ReasonCode "candidate_provider_final_state_invalid" -Reason "Promoted provider config final SHA/state did not match the registered candidate provider."))
            }
        }
    }
    else {
        $providerPromotionStatus = "not_requested"
    }

    if (-not $promotionFinalConfirmed -and $providerLockStatus -eq "acquired") {
        try {
            Restore-ProviderSnapshot -Snapshot $providerSnapshot | Out-Null
            $providerRestored = $true
            $providerPromoted = $false
            if (@($phases | Where-Object { $_.name -eq "provider_restore_or_promotion" }).Count -lt 1) {
                $phases.Add((New-CandidatePhase -Name "provider_restore_or_promotion" -Status "GO" -ReasonCode "provider_restored" -Reason "Previous provider config was restored after non-promoting or failed candidate proof."))
            }
        }
        catch {
            $providerRestoreFailed = $true
            $providerPromotionStatus = "NO-GO"
            $phases.Add((New-CandidatePhase -Name "provider_restore_or_promotion" -Status "NO-GO" -ReasonCode "provider_restore_failed" -Reason $_.Exception.Message))
        }
    }
    elseif (-not $promotionFinalConfirmed) {
        $phases.Add((New-CandidatePhase -Name "provider_restore_or_promotion" -Status "NO-GO" -ReasonCode "provider_lock_not_acquired" -Reason "Provider restore was not attempted because the provider mutation lock was not acquired."))
    }
}

try {
    $finalState = Get-ProviderFinalStateSummary -Path $providerPath -Snapshot $providerSnapshot -CandidateSha256 $candidateProviderSha256 -ProviderPromoted $providerPromoted -ProviderRestored $providerRestored
    $providerConfigSha256Final = [string]$finalState.sha256
    $providerFinalState = [string]$finalState.state
    $providerActiveAfterProof = [bool]$finalState.active
    if ($providerRestoreFailed) {
        $providerFinalState = "invalid"
    }
}
catch {
    $providerFinalState = "invalid"
    $phases.Add((New-CandidatePhase -Name "provider_final_state" -Status "NO-GO" -ReasonCode "provider_final_state_failed" -Reason $_.Exception.Message))
}
finally {
    if ($null -ne $providerLock) {
        Exit-ImmoAppProviderMutationLock -Lock $providerLock
        $providerLockReleased = $true
    }
}

$requiredForPromotion = @("artifact_inputs", "vendor_provenance", "package_inventory", "provider_registration", "runtime_detection", "hub_startup", "network_boundary", "backup_restore", "support_bundle")
$validationFailed = @($phases | Where-Object { $requiredForPromotion -contains $_.name -and $_.status -ne "GO" })
$candidateValidationStatus = if ($validationFailed.Count -eq 0) { "GO" } else { "NO-GO" }
$proofResult = "NO-GO"
$agencyInstallStatus = "NO_GO"
$reasonCode = "managed_runtime_candidate_proof_incomplete"
if ($missing.Count -gt 0) {
    $reasonCode = "managed_runtime_candidate_missing_artifacts"
}
elseif ($providerRestoreFailed) {
    $reasonCode = "provider_restore_failed"
}
elseif ($candidateValidationStatus -eq "GO" -and -not $providerPromoted -and $providerPromotionStatus -eq "not_requested") {
    $reasonCode = "managed_runtime_candidate_validated_not_promoted"
}
elseif ($candidateValidationStatus -eq "GO" -and $providerPromoted -and $providerPromotionStatus -eq "GO" -and $providerActiveAfterProof -and $promotionFinalConfirmed) {
    $proofResult = "GO"
    $agencyInstallStatus = "GO"
    $reasonCode = "managed_runtime_candidate_ready"
}

$result = [ordered]@{
    kind = "immoapp_managed_runtime_candidate_proof"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    candidate_proof_run_id = $candidateProofRunId
    proof_result = $proofResult
    candidate_validation_status = $candidateValidationStatus
    provider_promotion_status = $providerPromotionStatus
    provider_active_after_proof = $providerActiveAfterProof
    agency_install_status = $agencyInstallStatus
    reason_code = $reasonCode
    provenance_source = $provenanceSource
    vendor_provenance_path = $effectiveProvenanceJson
    license_review_status = $LicenseReviewStatus
    provider_lock_status = $providerLockStatus
    provider_lock_released = $providerLockReleased
    provider_lock_path = if ($null -ne $providerLock) { [string]$providerLock.path } else { Get-ImmoAppProviderMutationLockPath }
    missing_artifacts = @($missing.ToArray())
    provider_snapshot = [ordered]@{
        path = [string]$providerSnapshot.path
        existed = [bool]$providerSnapshot.existed
        sha256 = [string]$providerSnapshot.sha256
    }
    provider_restored = $providerRestored
    provider_promoted = $providerPromoted
    provider_config_sha256_final = $providerConfigSha256Final
    provider_final_state = $providerFinalState
    candidate_provider_sha256 = $candidateProviderSha256
    phases = @($phases.ToArray())
}

if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $paths.LogsRoot "managed_runtime_candidate_proof.json"
}
Write-ImmoAppSafeJson -Path $OutputJson -Payload $result -ApprovedRoots @($paths.ConfigRoot, $paths.LogsRoot, $paths.RuntimeRoot) -Depth 12 | Out-Null
$result | ConvertTo-Json -Depth 12
Write-Host "Managed runtime candidate proof_result=$($result.proof_result) agency_install_status=$($result.agency_install_status)"
if ($result.proof_result -ne "GO") {
    exit 1
}
