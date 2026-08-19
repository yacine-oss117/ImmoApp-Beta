param()

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "checks_common.ps1")

$ctx = Initialize-ImmoAppChecksContext
$serverPython = $ctx.ServerPython
$clientPython = $ctx.ClientPython

function Invoke-NonGatingExternal {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Script
    )
    try {
        Invoke-External $Name $Script
    }
    catch {
        Write-Warning ("[NON-GATING] {0} failed: {1}" -f $Name, $_.Exception.Message)
    }
}

$env:IMMOAPP_ENFORCE_NO_SECRETS = "1"
$env:IMMOAPP_RUN_RESTORE_DRILL = "1"
$env:IMMOAPP_ENFORCE_SAST = "1"
$env:IMMOAPP_ENFORCE_DEP_AUDIT = "1"

Write-Host "`n[CHECKS: NIGHTLY] Starting scheduled heavy validation lane..." -ForegroundColor Cyan

& (Join-Path $PSScriptRoot "checks_full.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "checks_full.ps1 failed."
}

Write-Host "`n[CHECKS: NIGHTLY] Running restore, perf, DAST, and resiliency suites..." -ForegroundColor Yellow
Invoke-External "verify_restore_drill_assets.py" { & $serverPython scripts/verify_restore_drill_assets.py }
Invoke-External "verify_restore_drill_execution.py" { & $serverPython scripts/verify_restore_drill_execution.py }
Invoke-NonGatingExternal "ui_capture.py" { & $clientPython scripts/ui_capture.py --theme all }
if ($env:IMMOAPP_UPDATE_UI_BASELINE -eq "1") {
    Invoke-NonGatingExternal "verify_ui_regression.py --update-baseline" {
        & $clientPython scripts/verify_ui_regression.py --update-baseline
    }
}
if ($env:CI -and $env:CI -in @("1", "true", "True")) {
    Invoke-NonGatingExternal "verify_ui_regression.py" {
        & $clientPython scripts/verify_ui_regression.py --require-baseline
    }
}
else {
    Invoke-NonGatingExternal "verify_ui_regression.py" { & $clientPython scripts/verify_ui_regression.py }
}
Invoke-External "verify_sast.py" { & $serverPython scripts/verify_sast.py }
Invoke-External "verify_dependency_vulns.py" { & $serverPython scripts/verify_dependency_vulns.py }
Invoke-External "run_game_day_drill.py" { & $serverPython scripts/run_game_day_drill.py }
Invoke-External "verify_game_day_automation.py" { & $serverPython scripts/verify_game_day_automation.py }
Invoke-External "verify_dast_smoke.py" { & $serverPython scripts/verify_dast_smoke.py }
Invoke-External "verify_query_budgets.py" { & $serverPython scripts/verify_query_budgets.py }
Invoke-External "verify_load_baseline.py" { & $serverPython scripts/verify_load_baseline.py }
Invoke-External "verify_api_queue_baseline.py" { & $serverPython scripts/verify_api_queue_baseline.py }
Invoke-External "verify_openbao_ha_readiness.py" { & $serverPython scripts/verify_openbao_ha_readiness.py }
Invoke-External "verify_signoz_live_rules.py" { & $serverPython scripts/verify_signoz_live_rules.py }
Invoke-External "verify_business_spans_instrumented.py" { & $serverPython scripts/verify_business_spans_instrumented.py }
Invoke-External "verify_business_metrics_instrumented.py" { & $serverPython scripts/verify_business_metrics_instrumented.py }

Write-Host "TLA+ waves are intentionally excluded here. Run scripts/checks_tla.ps1 separately." -ForegroundColor DarkYellow

Write-Host "`n[CHECKS: NIGHTLY] PASS" -ForegroundColor Green
