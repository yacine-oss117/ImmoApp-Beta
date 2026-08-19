param(
    [Parameter(Mandatory = $true)][string]$ProvenanceJson,
    [string]$ExpectedSourceCommitSha = "",
    [string]$ExpectedExtractedInventorySha256 = "",
    [switch]$AllowNonCanonicalRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$status = "NO-GO"
$reasonCode = "managed_runtime_vendor_provenance_invalid"
$reason = ""
$manifest = @{}
try {
    $verified = Assert-ImmoAppManagedRuntimeVendorProvenance `
        -ProvenancePath $ProvenanceJson `
        -ExpectedSourceCommitSha $ExpectedSourceCommitSha `
        -ExpectedExtractedInventorySha256 $ExpectedExtractedInventorySha256 `
        -AllowNonCanonicalRoot:$AllowNonCanonicalRoot
    $status = "GO"
    $reasonCode = "managed_runtime_vendor_provenance_valid"
    $reason = "Vendor runtime provenance is valid."
    $manifest = $verified.manifest
}
catch {
    $reason = $_.Exception.Message
    if ($reason -match "^(?<code>[a-z0-9_]+)\|(?<message>.*)$") {
        $reasonCode = $Matches["code"]
        $reason = $Matches["message"]
    }
}

[ordered]@{
    kind = "immoapp_managed_runtime_vendor_provenance_verification"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    proof_result = $status
    reason_code = $reasonCode
    reason = $reason
    provenance_path = [System.IO.Path]::GetFullPath($ProvenanceJson)
    vendor_name = [string](Get-ImmoAppObjectValue -Data $manifest -Name "vendor_name")
    runtime_name = [string](Get-ImmoAppObjectValue -Data $manifest -Name "runtime_name")
    runtime_version = [string](Get-ImmoAppObjectValue -Data $manifest -Name "runtime_version")
    runtime_license = [string](Get-ImmoAppObjectValue -Data $manifest -Name "runtime_license")
    artifact_sha256 = [string](Get-ImmoAppObjectValue -Data $manifest -Name "artifact_sha256")
    extracted_inventory_sha256 = [string](Get-ImmoAppObjectValue -Data $manifest -Name "extracted_inventory_sha256")
    source_commit_sha = [string](Get-ImmoAppObjectValue -Data $manifest -Name "source_commit_sha")
} | ConvertTo-Json -Depth 8

if ($status -ne "GO") {
    exit 1
}
