param(
    [string]$OutputRoot = "",
    [string]$HubBaseUrl = "",
    [Alias("BackupRestoreProofJson")]
    [string]$BackupRestoreEvidenceJson = "",
    [switch]$RunBackupProof,
    [switch]$ValidateOnly,
    [switch]$StartHubForProof
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-GitCommitSha {
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

function New-LocalOnlyEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][string]$Reason,
        [hashtable]$Extra = @{}
    )
    $payload = [ordered]@{
        kind = $Kind
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        machine_name = $env:COMPUTERNAME
        windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        source_commit_sha = $script:commitSha
        installer_sha256 = $script:installerSha256
        installed_version = ""
        installed_build_identity = ""
        proof_result = "NO-GO"
        failure_reason = $Reason
        synthetic = $true
        proof_scope = "local_only"
    }
    foreach ($key in $Extra.Keys) {
        $payload[$key] = $Extra[$key]
    }
    $payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
    return $Path
}

function Add-Phase {
    param(
        [System.Collections.Generic.List[object]]$Phases,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Reason = "",
        [string]$Artifact = ""
    )
    $Phases.Add([ordered]@{
        name = $Name
        status = $Status
        reason = $Reason
        artifact = $Artifact
    })
}

function Get-ObjectValue {
    param(
        [object]$Data,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $Data) { return $null }
    $property = $Data.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Test-BackupRestoreEvidence {
    param([Parameter(Mandatory = $true)]$Evidence)
    $result = [string](Get-ObjectValue -Data $Evidence -Name "proof_result")
    $status = [string](Get-ObjectValue -Data $Evidence -Name "status")
    $isGo = ($result -eq "GO" -or $status -eq "GO")
    $restoreDb = [string](Get-ObjectValue -Data $Evidence -Name "restore_database")
    $restoreBucket = [string](Get-ObjectValue -Data $Evidence -Name "isolated_restore_bucket")
    $hashVerifiedRaw = Get-ObjectValue -Data $Evidence -Name "storage_objects_hash_verified"
    $sourceUsedRaw = Get-ObjectValue -Data $Evidence -Name "live_source_bucket_used_as_restore_target"
    $hashVerified = 0
    if ($null -ne $hashVerifiedRaw) {
        [void][int]::TryParse([string]$hashVerifiedRaw, [ref]$hashVerified)
    }
    $sourceUsed = ([string]$sourceUsedRaw).ToLowerInvariant() -in @("true", "1", "yes")
    $reasons = New-Object System.Collections.Generic.List[string]
    if (-not $isGo) { $reasons.Add("backup_restore_not_go") }
    if ([string]::IsNullOrWhiteSpace($restoreDb)) { $reasons.Add("missing_restore_database") }
    if ([string]::IsNullOrWhiteSpace($restoreBucket) -or -not $restoreBucket.StartsWith("immoapp-restore-drill-")) {
        $reasons.Add("missing_isolated_restore_bucket")
    }
    if ($hashVerified -le 0) { $reasons.Add("missing_object_hash_verification") }
    if ($sourceUsed) { $reasons.Add("source_bucket_used_as_restore_target") }
    return [ordered]@{
        valid = ($reasons.Count -eq 0)
        reason_code = if ($reasons.Count -eq 0) { "backup_restore_verified" } else { ($reasons.ToArray() -join ";") }
    }
}

if ($ValidateOnly -and $StartHubForProof) {
    throw "ValidateOnly and StartHubForProof are mutually exclusive."
}
if (-not $ValidateOnly -and -not $StartHubForProof) {
    $ValidateOnly = $true
}

$repoRoot = (Get-ImmoAppRepoRoot).Path
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repoRoot (Join-Path ".tmp" (Join-Path "hub_m1_local_proof" (Get-Date -Format "yyyyMMdd_HHmmss")))
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$script:commitSha = Get-GitCommitSha
$script:installerSha256 = "0" * 64
$phases = New-Object System.Collections.Generic.List[object]

$runtimeJson = Join-Path $OutputRoot "hub_runtime_detection.json"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "detect_hub_runtime.ps1") -OutputJson $runtimeJson | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Runtime detection failed." }
$runtime = Get-Content -LiteralPath $runtimeJson -Raw | ConvertFrom-Json
Add-Phase -Phases $phases -Name "runtime_detection" -Status ([string]$runtime.agency_install_status) -Reason ([string]$runtime.reason) -Artifact $runtimeJson
$runtimeProofOnly = ([string](Get-ImmoAppObjectValue -Data $runtime.provider -Name "proof_only")).ToLowerInvariant() -in @("true", "1")
$providerStatus = if (
    [string]$runtime.runtime_dependency_mode -eq "managed_container_runtime" -and
    [string]$runtime.agency_install_status -eq "GO" -and
    [string]$runtime.provider_validation_status -eq "valid" -and
    [string]$runtime.reason_code -eq "managed_runtime_ready" -and
    -not $runtimeProofOnly
) { "GO" } else { "NO-GO" }
$providerReason = if ($providerStatus -eq "GO") { "" } else { "Managed hidden runtime provider is not verified. mode=$($runtime.runtime_dependency_mode) reason=$($runtime.reason)" }
Add-Phase -Phases $phases -Name "runtime_provider_proof" -Status $providerStatus -Reason $providerReason -Artifact $runtimeJson

$setupJson = Join-Path $OutputRoot "hub_setup_result.json"
$setupArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "setup_office_hub.ps1"), "-Role", "HubDesktop", "-OutputJson", $setupJson)
if ($ValidateOnly) {
    $setupArgs += "-ValidateOnly"
}
elseif ($StartHubForProof) {
    $setupArgs += "-StartHub"
}
& powershell @setupArgs | Out-Null
$setupExit = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) {
    $reason = if ($StartHubForProof) { "stack_start_failed" } else { "HubDesktop setup validation failed." }
    Add-Phase -Phases $phases -Name "hub_setup" -Status "NO-GO" -Reason $reason -Artifact $setupJson
}
if (Test-Path -LiteralPath $setupJson) {
    $setup = Get-Content -LiteralPath $setupJson -Raw | ConvertFrom-Json
}
else {
    $setup = [pscustomobject]@{
        hub_base_url = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { Get-ImmoAppHubBaseUrl -PreferLan }
        proof_result = "NO-GO"
        failure_reason = if ($setupExit -ne 0) { "stack_start_failed" } else { "setup_evidence_missing" }
    }
}
$hubUrl = if ($HubBaseUrl) { $HubBaseUrl.TrimEnd("/") } else { [string]$setup.hub_base_url }
$setupPhaseName = if ($ValidateOnly) { "hub_setup_validate" } else { "hub_setup_start" }
if ($setupExit -eq 0) {
    Add-Phase -Phases $phases -Name $setupPhaseName -Status ([string]$setup.proof_result) -Reason ([string]$setup.failure_reason) -Artifact $setupJson
}

$statusJson = Join-Path $OutputRoot "hub_status_evidence.json"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "collect_hub_status_evidence.ps1") -HubBaseUrl $hubUrl -RuntimeDetectionJson $runtimeJson -OutputJson $statusJson -SourceCommitSha $commitSha -InstallerSha256 $installerSha256 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Hub status evidence collection failed." }
$status = Get-Content -LiteralPath $statusJson -Raw | ConvertFrom-Json

$networkJson = Join-Path $OutputRoot "hub_network_boundary_evidence.json"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_hub_network_boundary.ps1") -HubBaseUrl $hubUrl -RuntimeDetectionJson $runtimeJson -OutputJson $networkJson | Out-Null
$networkExit = $LASTEXITCODE
if (Test-Path -LiteralPath $networkJson) {
    $network = Get-Content -LiteralPath $networkJson -Raw | ConvertFrom-Json
    Add-Phase -Phases $phases -Name "network_boundary" -Status ([string]$network.proof_result) -Reason ([string]$network.failure_reason) -Artifact $networkJson
}
else {
    Add-Phase -Phases $phases -Name "network_boundary" -Status "NO-GO" -Reason "Network boundary verifier did not produce evidence. exit=$networkExit" -Artifact $networkJson
}

if (
    $StartHubForProof -and
    [string]$status.proof_result -ne "GO" -and
    [string]$status.status_reason_code -eq "health_endpoint_unreachable" -and
    (Test-Path -LiteralPath $networkJson)
) {
    $networkForStatus = Get-Content -LiteralPath $networkJson -Raw | ConvertFrom-Json
    if ([string]$networkForStatus.proof_result -eq "GO") {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "collect_hub_status_evidence.ps1") -HubBaseUrl $hubUrl -RuntimeDetectionJson $runtimeJson -OutputJson $statusJson -SourceCommitSha $commitSha -InstallerSha256 $installerSha256 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Hub status evidence refresh failed." }
        $status = Get-Content -LiteralPath $statusJson -Raw | ConvertFrom-Json
    }
}

$statusReason = [string]$status.failure_reason
$statusCode = [string]$status.status_reason_code
if (-not [string]::IsNullOrWhiteSpace($statusCode) -and $status.proof_result -ne "GO") {
    $statusReason = "$statusCode $statusReason"
}
Add-Phase -Phases $phases -Name "hub_status" -Status ([string]$status.proof_result) -Reason $statusReason -Artifact $statusJson

$supportOutput = Join-Path $OutputRoot "support"
New-Item -ItemType Directory -Path $supportOutput -Force | Out-Null
$supportText = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "collect_desktop_support_bundle.ps1") -OutputDir $supportOutput
if ($LASTEXITCODE -ne 0) { throw "Support bundle collection failed." }
$supportBundlePath = (($supportText | Select-Object -Last 1 | Out-String).Trim())
$supportSha = if ($supportBundlePath -and (Test-Path -LiteralPath $supportBundlePath)) { Get-FileSha256 -Path $supportBundlePath } else { "" }
$supportManifestJson = Join-Path $OutputRoot "support_bundle_manifest.json"
[ordered]@{
    kind = "immoapp_support_bundle_manifest"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    source_commit_sha = $commitSha
    installer_sha256 = $installerSha256
    installed_version = ""
    installed_build_identity = ""
    proof_result = if ($supportSha) { "GO" } else { "NO-GO" }
    failure_reason = if ($supportSha) { "" } else { "Support bundle path/hash was not produced." }
    bundle_path = $supportBundlePath
    bundle_sha256 = $supportSha
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $supportManifestJson -Encoding UTF8
Add-Phase -Phases $phases -Name "support_bundle" -Status $(if ($supportSha) { "GO" } else { "NO-GO" }) -Artifact $supportManifestJson

$installJson = Join-Path $OutputRoot "hub_install_evidence.json"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "collect_hub_install_evidence.ps1") -InstallRole hub_desktop -HubBaseUrl $hubUrl -OutputJson $installJson -RuntimeDetectionJson $runtimeJson -StatusEvidenceJson $statusJson -SupportBundlePath $supportBundlePath -SourceCommitSha $commitSha -InstallerSha256 $installerSha256 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Hub install evidence collection failed." }
$install = Get-Content -LiteralPath $installJson -Raw | ConvertFrom-Json
Add-Phase -Phases $phases -Name "hub_install" -Status ([string]$install.proof_result) -Reason ([string]$install.failure_reason) -Artifact $installJson

if ($RunBackupProof) {
    $backupRoot = Join-Path $OutputRoot "backup"
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "backup_release_bundle.ps1") -OutputRoot $backupRoot -BundleName "hub_m1_local_proof" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Approved backup proof command failed." }
    $BackupRestoreEvidenceJson = Join-Path $backupRoot "backup_restore_proof.json"
    [ordered]@{
        kind = "immoapp_backup_restore_proof"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        proof_result = "NO-GO"
        failure_reason = "Backup bundle was created, but isolated restore proof was not run by this local proof helper."
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $BackupRestoreEvidenceJson -Encoding UTF8
}
elseif ([string]::IsNullOrWhiteSpace($BackupRestoreEvidenceJson)) {
    $BackupRestoreEvidenceJson = New-LocalOnlyEvidence -Path (Join-Path $OutputRoot "backup_restore_proof.json") -Kind "immoapp_backup_restore_proof" -Reason "missing_restore_evidence"
}
if (Test-Path -LiteralPath $BackupRestoreEvidenceJson) {
    $backupEvidence = Get-Content -LiteralPath $BackupRestoreEvidenceJson -Raw | ConvertFrom-Json
    if ([string](Get-ObjectValue -Data $backupEvidence -Name "failure_reason") -eq "missing_restore_evidence") {
        $backupStatus = "NO-GO"
        $backupReason = "missing_restore_evidence"
    }
    else {
        $backupValidation = Test-BackupRestoreEvidence -Evidence $backupEvidence
        $backupStatus = if ($backupValidation.valid) { "GO" } else { "NO-GO" }
        $backupReason = if ($backupValidation.valid) { "" } else { [string]$backupValidation.reason_code }
    }
    Add-Phase -Phases $phases -Name "backup_restore" -Status $backupStatus -Reason $backupReason -Artifact $BackupRestoreEvidenceJson
}
else {
    Add-Phase -Phases $phases -Name "backup_restore" -Status "NO-GO" -Reason "missing_restore_evidence" -Artifact $BackupRestoreEvidenceJson
}

$reachabilityJson = New-LocalOnlyEvidence -Path (Join-Path $OutputRoot "workstation_reachability.json") -Kind "immoapp_lan_workstation_reachability_proof" -Reason "Real workstation LAN proof was not supplied." -Extra @{ hub_base_url = $hubUrl; health_status = 0 }
$productJson = New-LocalOnlyEvidence -Path (Join-Path $OutputRoot "workstation_product_proof.json") -Kind "immoapp_manual_product_proof_evidence" -Reason "Real workstation product proof was not supplied." -Extra @{ owner_login_proof = $false; create_read_update_proof = $false; offer_photo_thumbnail_proof = $false }
$inventoryJson = New-LocalOnlyEvidence -Path (Join-Path $OutputRoot "installed_inventory.json") -Kind "immoapp_installed_inventory" -Reason "Installed inventory proof was not supplied."
$lifecycleJson = New-LocalOnlyEvidence -Path (Join-Path $OutputRoot "install_lifecycle.json") -Kind "immoapp_install_uninstall_reinstall_lifecycle" -Reason "Install/uninstall/reinstall lifecycle proof was not supplied."

$m1Json = Join-Path $OutputRoot "hub_beta_m1_go_no_go.json"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_hub_beta_m1_evidence.ps1") -HubInstallEvidenceJson $installJson -HubStatusEvidenceJson $statusJson -WorkstationReachabilityJson $reachabilityJson -WorkstationProductProofJson $productJson -BackupRestoreProofJson $BackupRestoreEvidenceJson -SupportBundleManifestJson $supportManifestJson -InstalledInventoryJson $inventoryJson -InstallLifecycleEvidenceJson $lifecycleJson -SourceCommitSha $commitSha -InstallerSha256 $installerSha256 -OutputJson $m1Json | Out-Null
$m1Exit = $LASTEXITCODE
if (Test-Path -LiteralPath $m1Json) {
    $m1 = Get-Content -LiteralPath $m1Json -Raw | ConvertFrom-Json
    Add-Phase -Phases $phases -Name "hub_beta_m1_go_no_go" -Status ([string]$m1.proof_result) -Reason ([string]$m1.failure_reason) -Artifact $m1Json
}
else {
    Add-Phase -Phases $phases -Name "hub_beta_m1_go_no_go" -Status "NO-GO" -Reason "M1 verifier did not produce output." -Artifact $m1Json
}

$failed = @($phases | Where-Object { $_.status -ne "GO" })
$summary = [ordered]@{
    kind = "immoapp_hub_m1_local_proof"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    source_commit_sha = $commitSha
    proof_result = if ($failed.Count -eq 0 -and $m1Exit -eq 0) { "GO" } else { "NO-GO" }
    failure_reason = if ($failed.Count -eq 0 -and $m1Exit -eq 0) { "" } else { (($failed | ForEach-Object { "$($_.name): $($_.reason)" }) -join " ") }
    phases = @($phases.ToArray())
    mode = if ($StartHubForProof) { "start_hub_for_proof" } else { "validate_only" }
    startup_attempted = [bool]$StartHubForProof
    observed_existing_hub_status = if ([string]$status.proof_result -eq "GO") { "GO" } else { "NO-GO" }
    started_hub_status = if ($StartHubForProof) { if ([string]$status.proof_result -eq "GO") { "GO" } else { "NO-GO" } } else { "not_applicable" }
    internal_hub_status = if ($StartHubForProof) { if ([string]$status.proof_result -eq "GO") { "GO" } else { "NO-GO" } } else { "not_applicable" }
    agency_install_status = if ($providerStatus -eq "GO" -and $m1Exit -eq 0) { "GO" } else { "NO-GO" }
    runtime_provider_status = $providerStatus
    real_agency_install_status = if ($providerStatus -eq "GO" -and $m1Exit -eq 0) { "GO" } else { "NO-GO" }
    real_lan_status = "NO-GO"
    backup_restore_status = if (@($phases | Where-Object { $_.name -eq "backup_restore" -and $_.status -eq "GO" }).Count -gt 0) { "GO" } else { "NO-GO" }
    output_root = (Resolve-Path -LiteralPath $OutputRoot).Path
}
$summaryJson = Join-Path $OutputRoot "hub_m1_local_proof_summary.json"
$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryJson -Encoding UTF8

Write-Host "Hub M1 local proof summary: $summaryJson"
foreach ($phase in $phases) {
    Write-Host ("{0}: {1} {2}" -f $phase.name, $phase.status, $phase.reason)
}
Write-Host "Hub M1 local proof_result=$($summary.proof_result)"
if ($summary.proof_result -ne "GO") {
    exit 1
}
