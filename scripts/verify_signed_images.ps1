param(
    [switch]$FailOnUnsignedTest
)

$ErrorActionPreference = "Stop"

$enforce = ($env:IMMOAPP_SUPPLYCHAIN_ENFORCE_SIGNED_IMAGES -in @("1", "true", "True"))
$manifestPath = "tools/security/image_signatures.json"

if (-not (Test-Path $manifestPath)) {
    if ($enforce) {
        throw "Missing $manifestPath while IMMOAPP_SUPPLYCHAIN_ENFORCE_SIGNED_IMAGES=1"
    }
    Write-Host "[verify_signed_images] Manifest missing; enforcement disabled -> skip"
    exit 0
}

$null = Get-Command cosign -ErrorAction Stop

if (-not $env:COSIGN_PUB_KEY) {
    if ($enforce) {
        throw "COSIGN_PUB_KEY is required when signed-image enforcement is enabled."
    }
    Write-Host "[verify_signed_images] COSIGN_PUB_KEY missing; enforcement disabled -> skip"
    exit 0
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$entries = @($manifest.entries)
if ($entries.Count -eq 0) {
    throw "No signed image entries in $manifestPath"
}

foreach ($entry in $entries) {
    $image = [string]$entry.image
    if (-not $image) {
        throw "Invalid image entry in $manifestPath"
    }
    Write-Host "[verify_signed_images] Verifying $image"
    & cosign verify --key $env:COSIGN_PUB_KEY $image | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Signature verification failed for $image"
    }
}

if ($FailOnUnsignedTest) {
    $testRef = "example.invalid/immoapp/unsigned@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    & cosign verify --key $env:COSIGN_PUB_KEY $testRef | Out-Null
    if ($LASTEXITCODE -eq 0) {
        throw "Negative test failed: unsigned image unexpectedly verified."
    }
    Write-Host "[verify_signed_images] Negative test passed (unsigned image rejected)."
}

Write-Host "[verify_signed_images] OK"
