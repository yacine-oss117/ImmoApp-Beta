param()

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "checks_common.ps1")

$ctx = Initialize-ImmoAppChecksContext
$serverPython = $ctx.ServerPython
$clientPython = $ctx.ClientPython
$depAuditScript = Join-Path (Get-ImmoAppRepoRoot) "scripts\verify_dependency_vulns.py"
$isCi = $env:CI -and $env:CI -in @("1", "true", "True")
$includePrInFull = $env:IMMOAPP_INCLUDE_PR_IN_FULL -and $env:IMMOAPP_INCLUDE_PR_IN_FULL -in @("1", "true", "True")

if (-not $env:IMMOAPP_ENFORCE_NO_SECRETS) {
    $env:IMMOAPP_ENFORCE_NO_SECRETS = "1"
}
if (-not $env:IMMOAPP_ENFORCE_SAST) {
    $env:IMMOAPP_ENFORCE_SAST = "0"
}
if (-not $env:IMMOAPP_ENFORCE_DEP_AUDIT) {
    $env:IMMOAPP_ENFORCE_DEP_AUDIT = "1"
}

Write-Host "`n[CHECKS: FULL] Starting merge/release lane..." -ForegroundColor Cyan

if ($includePrInFull) {
    Write-Host "[CHECKS: FULL] IMMOAPP_INCLUDE_PR_IN_FULL=1 -> running PR lane first." -ForegroundColor DarkYellow
    & (Join-Path $PSScriptRoot "checks_pr.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "checks_pr.ps1 failed."
    }
}
else {
    Invoke-DjangoModelDriftCheck -Context $ctx
}
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

Write-Host "`n[CHECKS: FULL] Running server integration tests..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "test_server.ps1") `
    -PytestTarget "app/tests/server_tests" `
    -PytestMarker "integration or e2e or slow" `
    -SkipDjangoFirewall `
    -RunConnectionLeakTests
if ($LASTEXITCODE -ne 0) {
    throw "Integration server test lane failed."
}

Write-Host "`n[CHECKS: FULL] Running full UI tests..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "test_ui.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "UI tests failed."
}

Write-Host "`n[CHECKS: FULL] Running live auth smoke (server + client login)..." -ForegroundColor Yellow
Invoke-External "check_live_auth_smoke.py" {
    & $clientPython scripts/check_live_auth_smoke.py --server-python $serverPython --seed
}

Write-Host "`n[CHECKS: FULL] Running security/contract guardrails..." -ForegroundColor Yellow
$skipProdConfig = $env:IMMOAPP_SKIP_PROD_CONFIG -and $env:IMMOAPP_SKIP_PROD_CONFIG -in @("1", "true", "True")
if ($skipProdConfig) {
    Write-Host "Skipping verify_prod_config.py because IMMOAPP_SKIP_PROD_CONFIG=1." -ForegroundColor DarkYellow
}
else {
    Invoke-External "verify_prod_config.py" { & $serverPython scripts/verify_prod_config.py }
}
Invoke-External "verify_namespace_consistency.py" { & $serverPython scripts/verify_namespace_consistency.py }
Invoke-External "verify_local_env_safety.py" { & $serverPython scripts/verify_local_env_safety.py }
Invoke-External "verify_openbao_runtime_env.py" { & $serverPython scripts/verify_openbao_runtime_env.py }
Invoke-External "verify_openbao_agent_compose.py" { & $serverPython scripts/verify_openbao_agent_compose.py }
Invoke-External "verify_no_secrets.py" { & $serverPython scripts/verify_no_secrets.py }
Invoke-External "verify_no_exception_leakage.py" { & $serverPython scripts/verify_no_exception_leakage.py }
Invoke-External "build backend image for Docker dependency audit" {
    & powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action build-app
}
Invoke-External "verify_dependency_vulns.py" {
    $previousDockerAuditRequired = $env:IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND
    try {
        $env:IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND = "1"
        & $serverPython $depAuditScript
    }
    finally {
        if ($null -eq $previousDockerAuditRequired) {
            Remove-Item Env:IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND -ErrorAction SilentlyContinue
        }
        else {
            $env:IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND = $previousDockerAuditRequired
        }
    }
}
Invoke-External "verify_api_contract_policies.py" { & $serverPython scripts/verify_api_contract_policies.py }
Invoke-External "verify_no_direct_otel_metrics.py" { & $serverPython scripts/verify_no_direct_otel_metrics.py }
Invoke-External "verify_ui_copy_contract.py" { & $serverPython scripts/verify_ui_copy_contract.py }
Invoke-External "verify_domain_integration_matrix.py" { & $serverPython scripts/verify_domain_integration_matrix.py }
Invoke-External "verify_ops_posture.py" { & $serverPython scripts/verify_ops_posture.py }
Invoke-External "verify_write_policies.py" { & $serverPython scripts/verify_write_policies.py }
Invoke-External "verify_infrastructure_hardening.py" { & $serverPython scripts/verify_infrastructure_hardening.py }
$freshChainMode = if ($env:IMMOAPP_FRESH_CHAIN_MODE) { $env:IMMOAPP_FRESH_CHAIN_MODE } else { "auto" }
Invoke-External "verify_alembic_fresh_chain.py" { & $serverPython scripts/verify_alembic_fresh_chain.py --python $serverPython --mode $freshChainMode --docker-service web }
Invoke-External "verify_security_schema.py" { & $serverPython scripts/verify_security_schema.py }
Invoke-External "verify_schema.py" { & $serverPython scripts/verify_schema.py }

Write-Host "`n[CHECKS: FULL] PASS" -ForegroundColor Green
