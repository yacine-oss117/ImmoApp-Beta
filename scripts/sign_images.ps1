param(
    [string[]]$Images = @()
)

$ErrorActionPreference = "Stop"

if (-not $Images -or $Images.Count -eq 0) {
    $raw = $env:IMMOAPP_SIGN_IMAGES
    if ($raw) {
        $Images = $raw.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    }
}

if (-not $Images -or $Images.Count -eq 0) {
    Write-Host "[sign_images] No images configured (IMMOAPP_SIGN_IMAGES). Nothing to sign."
    exit 0
}

if (-not $env:COSIGN_KEY) {
    throw "COSIGN_KEY is required."
}

$null = Get-Command cosign -ErrorAction Stop

$outDir = "tools/security"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$manifestPath = Join-Path $outDir "image_signatures.json"

$entries = @()
foreach ($image in $Images) {
    Write-Host "[sign_images] Signing $image"
    & cosign sign --yes --key $env:COSIGN_KEY $image
    if ($LASTEXITCODE -ne 0) {
        throw "cosign sign failed for $image"
    }
    $entries += @{
        image = $image
        signed_at = (Get-Date).ToUniversalTime().ToString("o")
    }
}

$manifest = @{
    schema = "immoapp.supplychain.signatures.v1"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    entries = $entries
}

$manifest | ConvertTo-Json -Depth 6 | Out-File -FilePath $manifestPath -Encoding utf8
Write-Host "[sign_images] OK -> $manifestPath"
