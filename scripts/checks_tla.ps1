$ErrorActionPreference = "Stop"

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Script
    )
    & $Script
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

. (Join-Path $PSScriptRoot "common.ps1")
Set-ImmoAppSecurityEnv
Import-ImmoAppEnvFile

$VENV_PYTHON = Get-ImmoAppVenvPython -Kind server
if (-not (Test-Path $VENV_PYTHON)) {
    throw "Server venv python not found at $VENV_PYTHON"
}

Write-Host "`n[TLA+ VERIFICATION SUITE]" -ForegroundColor Cyan
Invoke-External "verify_tlc_ready.py" { & $VENV_PYTHON scripts/verify_tlc_ready.py }

Write-Host "-> Wave-1 TLA+ Verification..." -ForegroundColor Gray
Invoke-External "verify_tla_wave1.py" { & $VENV_PYTHON scripts/verify_tla_wave1.py }
Write-Host "-> Wave-2 TLA+ Verification..." -ForegroundColor Gray
Invoke-External "verify_tla_wave2.py" { & $VENV_PYTHON scripts/verify_tla_wave2.py }
Write-Host "-> Wave-3 TLA+ Verification..." -ForegroundColor Gray
Invoke-External "verify_tla_wave3.py" { & $VENV_PYTHON scripts/verify_tla_wave3.py }
Write-Host "-> Wave-4 TLA+ Verification..." -ForegroundColor Gray
Invoke-External "verify_tla_wave4.py" { & $VENV_PYTHON scripts/verify_tla_wave4.py }
Write-Host "-> Wave-5 TLA+ Verification..." -ForegroundColor Gray
Invoke-External "verify_tla_wave5.py" { & $VENV_PYTHON scripts/verify_tla_wave5.py }
Write-Host "-> Wave-6 TLA+ Verification..." -ForegroundColor Gray
Invoke-External "verify_tla_wave6.py" { & $VENV_PYTHON scripts/verify_tla_wave6.py }

Write-Host "`nTLA+ verification completed." -ForegroundColor Green
