param(
    [Parameter(Mandatory = $true)][string]$ArtifactPath,
    [Parameter(Mandatory = $true)][string]$ExtractedRuntimeRoot,
    [ValidateSet("zip")][string]$ArtifactKind = "zip",
    [Parameter(Mandatory = $true)][string]$VendorName,
    [Parameter(Mandatory = $true)][string]$RuntimeName,
    [Parameter(Mandatory = $true)][string]$RuntimeVersion,
    [Parameter(Mandatory = $true)][string]$RuntimeLicense,
    [string]$RuntimeSourceUrl = "",
    [string]$InternalSourceReference = "",
    [Parameter(Mandatory = $true)][string]$ApprovalReason,
    [string]$SourceCommitSha = "",
    [string]$OutputJson = "",
    [switch]$ApprovedByImmoApp,
    [string]$LicenseDistributionAllowed = "false",
    [string]$LicenseReviewStatus = "",
    [string]$ApprovedBy = "",
    [string]$ApprovedAtUtc = "",
    [switch]$ProofOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

if (-not $ApprovedByImmoApp) {
    throw "Vendor runtime provenance requires -ApprovedByImmoApp."
}
if ($ArtifactKind -ne "zip") {
    throw "Vendor runtime provenance currently supports only artifact_kind=zip."
}
$licenseDistributionAllowedBool = $LicenseDistributionAllowed.Trim().ToLowerInvariant() -in @("1", "true", "yes", "on")
if (-not $licenseDistributionAllowedBool) {
    throw "Vendor runtime provenance requires -LicenseDistributionAllowed true."
}
if ($LicenseReviewStatus -ne "approved") {
    throw "Vendor runtime provenance requires -LicenseReviewStatus approved."
}
if ([string]::IsNullOrWhiteSpace($ApprovedBy)) {
    throw "Vendor runtime provenance requires -ApprovedBy."
}
if ([string]::IsNullOrWhiteSpace($ApprovedAtUtc)) {
    $ApprovedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
}
try {
    [void][DateTimeOffset]::Parse($ApprovedAtUtc)
}
catch {
    throw "ApprovedAtUtc must be an ISO-8601 timestamp."
}
if ([string]::IsNullOrWhiteSpace($RuntimeSourceUrl) -and [string]::IsNullOrWhiteSpace($InternalSourceReference)) {
    throw "Vendor runtime provenance requires RuntimeSourceUrl or InternalSourceReference."
}
if ([string]::IsNullOrWhiteSpace($SourceCommitSha)) {
    $SourceCommitSha = (& git -C (Get-ImmoAppRepoRoot).Path rev-parse HEAD 2>$null | Out-String).Trim().ToLowerInvariant()
}
if ($SourceCommitSha -notmatch "^[0-9a-f]{40}$") {
    throw "SourceCommitSha must be a 40-character lowercase git SHA."
}
if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
    throw "ArtifactPath does not exist: $ArtifactPath"
}
if (-not (Test-Path -LiteralPath $ExtractedRuntimeRoot -PathType Container)) {
    throw "ExtractedRuntimeRoot does not exist: $ExtractedRuntimeRoot"
}
if (Test-ImmoAppPathHasReparsePoint -Path $ArtifactPath) {
    throw "ArtifactPath contains a reparse point, symlink, or junction: $ArtifactPath"
}
if (Test-ImmoAppPathHasReparsePoint -Path $ExtractedRuntimeRoot) {
    throw "ExtractedRuntimeRoot contains a reparse point, symlink, or junction: $ExtractedRuntimeRoot"
}

$treeInventory = Get-ImmoAppStrictRuntimeTreeInventory -Root $ExtractedRuntimeRoot -RequireNonEmpty
$zipInventory = Get-ImmoAppSafeZipInventory -ArtifactPath $ArtifactPath
$treeInventorySha = [string]$treeInventory.sha256
$zipInventorySha = [string]$zipInventory.sha256
if ($zipInventorySha -ne $treeInventorySha) {
    throw "managed_runtime_vendor_inventory_hash_mismatch|Vendor ZIP extracted inventory does not match ExtractedRuntimeRoot inventory."
}

$paths = Get-ImmoAppRuntimePaths
if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $paths.ConfigRoot "managed_runtime_vendor_provenance.json"
}
$outputFull = [System.IO.Path]::GetFullPath($OutputJson)
if (
    -not (Test-ImmoAppPathUnderRoot -Root $paths.RuntimeRoot -Path $outputFull) -and
    -not (Test-ImmoAppPathUnderRoot -Root $paths.ConfigRoot -Path $outputFull)
) {
    throw "OutputJson must be under the active ImmoApp runtime or config root: $outputFull"
}
$outputParent = Split-Path -Parent $outputFull
if ($outputParent -and (Test-Path -LiteralPath $outputParent) -and (Test-ImmoAppPathHasReparsePoint -Path $outputParent)) {
    throw "OutputJson parent contains a reparse point, symlink, or junction: $outputParent"
}
if ($outputParent -and -not (Test-Path -LiteralPath $outputParent)) {
    New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
}

$artifactFull = [System.IO.Path]::GetFullPath($ArtifactPath)
$payload = [ordered]@{
    kind = "immoapp_managed_runtime_vendor_provenance"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    vendor_name = $VendorName
    runtime_name = $RuntimeName
    runtime_version = $RuntimeVersion
    runtime_license = $RuntimeLicense
    artifact_kind = $ArtifactKind
    runtime_source_url = $RuntimeSourceUrl
    internal_source_reference = $InternalSourceReference
    artifact_path = $artifactFull
    artifact_sha256 = Get-ImmoAppFileSha256 -Path $artifactFull
    artifact_bytes = [int64](Get-Item -LiteralPath $artifactFull).Length
    extracted_inventory_sha256 = $zipInventorySha
    approved_by_immoapp = $true
    license_distribution_allowed = $true
    license_review_status = $LicenseReviewStatus
    proof_only = [bool]$ProofOnly
    approved_by = $ApprovedBy
    approved_at_utc = $ApprovedAtUtc
    approval_reason = $ApprovalReason
    source_commit_sha = $SourceCommitSha
    generated_by_machine = $env:COMPUTERNAME
    generated_by_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}

Write-ImmoAppSafeJson -Path $outputFull -Payload $payload -ApprovedRoots @($paths.RuntimeRoot, $paths.ConfigRoot) -Depth 8 | Out-Null
$payload | ConvertTo-Json -Depth 8
