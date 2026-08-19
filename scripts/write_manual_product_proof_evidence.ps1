param(
    [Parameter(Mandatory = $true)][string]$FreshEvidenceJson,
    [Parameter(Mandatory = $true)][string]$OutputJson,
    [Parameter(Mandatory = $true)][string]$SupportBundlePath,
    [switch]$OwnerLoginConfirmed,
    [switch]$CrudConfirmed,
    [switch]$OfferPhotoThumbnailConfirmed,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

foreach ($name in @("OwnerLoginConfirmed", "CrudConfirmed", "OfferPhotoThumbnailConfirmed")) {
    if (-not (Get-Variable -Name $name -ValueOnly).IsPresent) {
        throw "Manual product proof requires explicit -$name after the operator actually observed it."
    }
}
if (-not (Test-Path -LiteralPath $FreshEvidenceJson)) {
    throw "Fresh-machine evidence JSON not found: $FreshEvidenceJson"
}
$fresh = Get-Content -LiteralPath $FreshEvidenceJson -Raw | ConvertFrom-Json
if ([string]$fresh.kind -ne "immoapp_fresh_machine_install_evidence") {
    throw "Fresh-machine evidence has wrong kind."
}
if (-not (Test-Path -LiteralPath $SupportBundlePath)) {
    throw "Support bundle path not found: $SupportBundlePath"
}

$evidence = [ordered]@{
    kind = "immoapp_manual_product_proof_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    operator_windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    machine_name = $env:COMPUTERNAME
    fresh_machine_evidence_path = (Resolve-Path -LiteralPath $FreshEvidenceJson).Path
    fresh_machine_evidence_sha256 = Get-FileSha256 -Path $FreshEvidenceJson
    support_bundle_path = (Resolve-Path -LiteralPath $SupportBundlePath).Path
    support_bundle_sha256 = Get-FileSha256 -Path $SupportBundlePath
    owner_login_proof = $OwnerLoginConfirmed.IsPresent
    create_read_update_proof = $CrudConfirmed.IsPresent
    offer_photo_thumbnail_proof = $OfferPhotoThumbnailConfirmed.IsPresent
    notes = $Notes
    mutation_routes_used = $false
}

$outputDir = Split-Path -Parent $OutputJson
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
$evidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
Write-Host "Manual product proof evidence JSON: $OutputJson"
Write-Host "Manual product proof mutation_routes_used=false"
