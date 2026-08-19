param()

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "checks_common.ps1")

$ctx = Initialize-ImmoAppChecksContext
$serverPython = $ctx.ServerPython
$clientPython = $ctx.ClientPython

Write-Host "`n[CHECKS: PR] Starting fast CI lane (lint + types + unit tests)" -ForegroundColor Cyan

Invoke-LintChecks -Context $ctx
Invoke-TypeChecks -Context $ctx
Invoke-DjangoModelDriftCheck -Context $ctx
Invoke-External "verify_requirements_lock.py" { & $serverPython scripts/verify_requirements_lock.py }
Invoke-External "verify_release_rollout_contract.py" { & $serverPython scripts/verify_release_rollout_contract.py }
Invoke-External "verify_runtime_contracts.py" { & $serverPython scripts/verify_runtime_contracts.py }
Invoke-External "verify_supply_chain_contract.py" { & $serverPython scripts/verify_supply_chain_contract.py }
Invoke-External "verify_api_route_reference.py" { & $serverPython scripts/verify_api_route_reference.py }
Invoke-External "verify_schema_authority_registry.py" { & $serverPython scripts/verify_schema_authority_registry.py }
Invoke-External "verify_no_blind_django_ddl_for_alembic_owned_tables.py" { & $serverPython scripts/verify_no_blind_django_ddl_for_alembic_owned_tables.py }
Invoke-External "verify_raw_sql_orm_mirror_contract.py" { & $serverPython scripts/verify_raw_sql_orm_mirror_contract.py }
Invoke-External "verify_state_only_mirror_contract.py" { & $serverPython scripts/verify_state_only_mirror_contract.py }
Invoke-External "verify_schema_authority_docs.py" { & $serverPython scripts/verify_schema_authority_docs.py }
Invoke-External "verify_db_table_catalog.py" { & $serverPython scripts/verify_db_table_catalog.py }
Write-Host "`n[CHECKS: PR] Enforcing OpenTelemetry metrics wrapper (no direct get_meter usage)..." -ForegroundColor Yellow
Invoke-External "verify_no_direct_otel_metrics.py" { & $serverPython scripts/verify_no_direct_otel_metrics.py }
Invoke-External "verify_ui_copy_contract.py" { & $serverPython scripts/verify_ui_copy_contract.py }

Write-Host "`n[CHECKS: PR] Running server unit tests (integration excluded)..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "test_server.ps1") `
    -PytestTarget "app/tests/server_tests" `
    -PytestMarker "not integration and not slow and not perf and not e2e and not nightly"
if ($LASTEXITCODE -ne 0) {
    throw "Unit server test lane failed."
}

Write-Host "`n[CHECKS: PR] Running importer unit tests (fast subset)..." -ForegroundColor Yellow
Invoke-External "pytest tests/test_importer (fast subset)" {
    & $serverPython -m pytest tests/test_importer -k "not end_to_end"
}

Write-Host "`n[CHECKS: PR] Running lightweight UI startup smoke..." -ForegroundColor Yellow
$env:IMMOAPP_STARTUP_LIGHT = "1"
Invoke-External "check_startup.py" { & $clientPython scripts/check_startup.py }

Write-Host "`n[CHECKS: PR] PASS" -ForegroundColor Green
