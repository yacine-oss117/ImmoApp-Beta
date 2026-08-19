param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [string]$SignerName = "Yacine Larbaoui",
    [string]$OutputSignedInstallerPath = "",
    [switch]$AllowReplaceSignedInstaller
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Assert-SigningPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    $releaseRoot = Join-Path (Get-ImmoAppCanonicalRuntimePaths).AppDataRoot "release_artifacts"
    $repoTmp = Join-Path (Get-ImmoAppRepoRoot) ".tmp"
    $allowed = (Test-ImmoAppPathUnderRoot -Root $releaseRoot -Path $full) -or (Test-ImmoAppPathUnderRoot -Root $repoTmp -Path $full)
    if (-not $allowed) {
        throw "$Label path must be under ProgramData release_artifacts or repo .tmp: $full"
    }
    $parent = Split-Path -Parent $full
    if ($parent -and (Test-Path -LiteralPath $parent) -and (Test-ImmoAppPathHasReparsePoint -Path $parent)) {
        throw "$Label parent contains a reparse point, symlink, or junction: $parent"
    }
    if ((Test-Path -LiteralPath $full) -and (Test-ImmoAppPathHasReparsePoint -Path $full)) {
        throw "$Label path contains a reparse point, symlink, or junction: $full"
    }
    return $full
}

if ($SignerName -notlike "*Yacine Larbaoui*") {
    throw "self_signed_signer_subject_invalid|SignerName must include Yacine Larbaoui."
}

$sourceInstaller = Assert-SigningPath -Path $InstallerPath -Label "Installer"
if (-not (Test-Path -LiteralPath $sourceInstaller -PathType Leaf)) {
    throw "self_signed_installer_missing|InstallerPath does not exist: $sourceInstaller"
}
$sourceDir = Split-Path -Parent $sourceInstaller
$signedInstaller = if ($OutputSignedInstallerPath) {
    Assert-SigningPath -Path $OutputSignedInstallerPath -Label "Signed installer"
}
else {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($sourceInstaller)
    $ext = [System.IO.Path]::GetExtension($sourceInstaller)
    Join-Path $sourceDir "$base.self-signed$ext"
}
$signedInstaller = [System.IO.Path]::GetFullPath($signedInstaller)
if ((Test-Path -LiteralPath $signedInstaller) -and -not $AllowReplaceSignedInstaller.IsPresent) {
    throw "self_signed_output_exists|Signed installer already exists; pass -AllowReplaceSignedInstaller to replace it: $signedInstaller"
}

$unsignedSha = Get-ImmoAppFileSha256 -Path $sourceInstaller
Copy-Item -LiteralPath $sourceInstaller -Destination $signedInstaller -Force
$subject = "CN=$SignerName"
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $subject -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1
if (-not $cert) {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -KeyUsage DigitalSignature `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears(3)
}

$rootCert = Get-ChildItem Cert:\CurrentUser\Root | Where-Object { $_.Thumbprint -eq $cert.Thumbprint } | Select-Object -First 1
if (-not $rootCert) {
    $tempCert = Join-Path $env:TEMP ("immoapp-self-sign-" + [Guid]::NewGuid().ToString("N") + ".cer")
    try {
        Export-Certificate -Cert $cert -FilePath $tempCert | Out-Null
        Import-Certificate -FilePath $tempCert -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $tempCert) { Remove-Item -LiteralPath $tempCert -Force }
    }
}

$signature = Set-AuthenticodeSignature -FilePath $signedInstaller -Certificate $cert -HashAlgorithm SHA256
$postSignature = $null
$signatureReadError = ""
for ($attempt = 1; $attempt -le 20; $attempt += 1) {
    try {
        $postSignature = Get-AuthenticodeSignature -LiteralPath $signedInstaller
        $signatureReadError = ""
        break
    }
    catch {
        $signatureReadError = $_.Exception.Message
        Start-Sleep -Milliseconds 500
    }
}
if (-not $postSignature) {
    throw "self_signed_signature_read_failed|Unable to read Authenticode signature after signing: $signatureReadError"
}
$signedSha = Get-ImmoAppFileSha256 -Path $signedInstaller
$proofResult = if ($postSignature.Status -eq "Valid" -and $postSignature.SignerCertificate.Thumbprint -eq $cert.Thumbprint) { "GO" } else { "NO-GO" }
$reasonCode = if ($proofResult -eq "GO") { "self_signed_local_internal_signature_go" } else { "self_signed_local_internal_signature_invalid" }

$evidence = [ordered]@{
    kind = "immoapp_installer_self_signed_signature_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    proof_result = $proofResult
    reason_code = $reasonCode
    signature_type = "self_signed_local_internal"
    local_internal_signed_status = if ($proofResult -eq "GO") { "GO" } else { "NO-GO" }
    public_beta_distribution_status = "NO-GO self-signed local/internal only"
    source_installer_path = $sourceInstaller
    signed_installer_path = $signedInstaller
    source_commit_sha = ""
    unsigned_installer_sha256 = $unsignedSha
    signed_installer_sha256 = $signedSha
    signer_subject = [string]$cert.Subject
    certificate_thumbprint = [string]$cert.Thumbprint
    authenticode_status = [string]$postSignature.Status
    authenticode_status_message = [string]$postSignature.StatusMessage
    set_authenticode_status = [string]$signature.Status
}

$summaryPath = Join-Path $sourceDir ([System.IO.Path]::GetFileNameWithoutExtension($sourceInstaller) + ".summary.json")
if (Test-Path -LiteralPath $summaryPath -PathType Leaf) {
    try {
        $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        $evidence.source_commit_sha = [string]$summary.source_commit_sha
    }
    catch {
        $evidence.summary_parse_warning = $_.Exception.Message
    }
}

$evidencePath = "$sourceInstaller.self_signed_signature_evidence.json"
$write = Write-ImmoAppSafeJson -Path $evidencePath -Payload $evidence -ApprovedRoots @($sourceDir, (Join-Path (Get-ImmoAppRepoRoot) ".tmp")) -Depth 8
$evidence.evidence_path = $write.path
$evidence.evidence_sha256 = $write.sha256
$evidence | ConvertTo-Json -Depth 8
if ($proofResult -ne "GO") { exit 1 }
