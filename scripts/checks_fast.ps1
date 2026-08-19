param()

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "checks_common.ps1")

$ctx = Initialize-ImmoAppChecksContext

Write-Host "`n[CHECKS: FAST] Lint + formatting guardrails" -ForegroundColor Cyan
Invoke-LintChecks -Context $ctx

Write-Host "`n[CHECKS: FAST] PASS" -ForegroundColor Green
