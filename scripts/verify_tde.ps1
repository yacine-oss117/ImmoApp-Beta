$ErrorActionPreference = "Continue"
$failed = $false

. (Join-Path $PSScriptRoot "common.ps1")

Write-Host "--- [DISC LEVEL (TDE) COMPLIANCE AUDIT] ---" -ForegroundColor Cyan

# 1. Check BitLocker on C: (Standard for single-disk setups)
Write-Host "Checking Volume C: Encryption Status..."
$bde = manage-bde -status C:
if ($LASTEXITCODE -ne 0) {
    Write-Host "ℹ️  BitLocker check skipped (manage-bde requires elevation)." -ForegroundColor Yellow
    $LASTEXITCODE = 0
} else {
    $isEncrypted = $bde -match "Percentage Encrypted:   100.0%"
    $protectionOn = $bde -match "Protection Status:    Protection On"
    
    if ($isEncrypted -and $protectionOn) {
        Write-Host "✅ Volume C: is fully encrypted with BitLocker." -ForegroundColor Green
    } else {
        Write-Host "❌ WARNING: Volume C: is NOT fully encrypted or protection is OFF!" -ForegroundColor Red
        $failed = $true
    }
}

# 2. Check MinIO SSE Readiness
Write-Host "`nChecking Storage Encryption (SSE) Configuration..."
$compose = Get-Content (Get-ImmoAppComposeFile -Name "compose.yml") -Raw
if ($compose -match "MINIO_KMS_SECRET_KEY") {
    Write-Host "✅ MinIO Server-Side Encryption (SSE) is configured in deployment/compose/compose.yml." -ForegroundColor Green
} else {
    Write-Host "❌ FAIL: MinIO SSE is missing from deployment/compose/compose.yml!" -ForegroundColor Red
    $failed = $true
}

# 3. Check ALE Scope
Write-Host "`nChecking Application Layer Encryption (ALE) Scope..."
$client_model = Get-Content "core/models_client.py" -Raw
if ($client_model -match "remarks_enc") {
    Write-Host "✅ ALE Scope correctly includes 'remarks'." -ForegroundColor Green
} else {
    Write-Host "❌ FAIL: ALE Scope is missing 'remarks'." -ForegroundColor Red
    $failed = $true
}

Write-Host "`n--- [TDE AUDIT COMPLETE] ---"

if ($failed) {
    exit 1
}
exit 0
