from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_reset_e2e_environment_exposes_required_safe_modes() -> None:
    text = _read("scripts/reset_e2e_environment.ps1")
    required_tokens = (
        '[ValidateSet("check", "reset")]',
        "[switch]$CleanArtifacts",
        "[switch]$CleanPytestCache",
        "[switch]$CleanDockerApp",
        "[switch]$RestartDocker",
        "[switch]$KillStaleDesktopProcesses",
        "[switch]$KillStaleServerProcesses",
        "[int]$WarnFreeMemoryGb = 6",
        "[int]$MinCriticalFreeMemoryGb = 1",
        "[int]$MinCommitHeadroomGb = 2",
        "[int]$MinFreeMemoryGb = -1",
        "[switch]$RequireDocker",
        "[switch]$RequireInteractiveDesktop",
        "[switch]$RequireBackend",
        "[bool]$CheckClientQtImport = $true",
        "function Assert-SafeCleanupTarget",
        "function Invoke-RequiredSpawnCanary",
        "function Get-E2EStaleProcesses",
        "function Stop-E2EStaleProcesses",
        "function Invoke-BackendIdentityPreflight",
    )
    for token in required_tokens:
        assert token in text


def test_reset_e2e_environment_has_no_broad_deletes_or_process_kills() -> None:
    text = _read("scripts/reset_e2e_environment.ps1")
    forbidden_tokens = (
        "Remove-Item $env:TEMP",
        "Remove-Item -Path $env:TEMP",
        "Remove-Item -LiteralPath $env:TEMP",
        "Remove-Item C:\\ProgramData\\ImmoApp",
        "Remove-Item -Path C:\\ProgramData\\ImmoApp",
        "Remove-Item -LiteralPath C:\\ProgramData\\ImmoApp",
        "Stop-Process -Name python",
        "Stop-Process -Name powershell",
        "Stop-Process -Name docker",
    )
    for token in forbidden_tokens:
        assert token not in text
    assert "Stop-Process -Id $proc.pid" in text


def test_reset_e2e_environment_process_selection_requires_command_line_ownership() -> None:
    text = _read("scripts/reset_e2e_environment.ps1")
    assert "wmic.exe" in text
    assert "CommandLine" in text
    assert '$cmd.Contains("\\app\\main.py")' in text
    assert '$cmd.Contains("\\app\\tests\\e2e_desktop")' in text
    assert "desktop_e2e_artifact_root" in text
    assert "repo_app_main" in text


def test_reset_e2e_environment_uses_adaptive_memory_policy() -> None:
    text = _read("scripts/reset_e2e_environment.ps1")
    assert "warning threshold is $WarnFreeMemoryGb GB" in text
    assert 'Add-RunnerWarning "Free physical memory is $script:freeMemoryGb GB' in text
    assert "Free physical memory is critically low" in text
    assert "$script:freeMemoryGb -lt $MinCriticalFreeMemoryGb" in text
    assert "Windows commit/page-file headroom is $script:commitHeadroomGb GB" in text
    assert "$script:commitHeadroomGb -lt $MinCommitHeadroomGb" in text
    assert (
        "Windows commit/page-file headroom was unavailable; relying on process spawn canaries."
        in text
    )
    assert "required minimum is $MinFreeMemoryGb GB" not in text


def test_reset_e2e_environment_keeps_spawn_canaries_as_hard_gates() -> None:
    text = _read("scripts/reset_e2e_environment.ps1")
    assert "spawn_canaries = $spawnCanaries" in text
    assert 'Invoke-RequiredSpawnCanary -Name "powershell"' in text
    assert 'CanaryName "server_python"' in text
    assert 'CanaryName "client_python"' in text
    assert 'Invoke-RequiredSpawnCanary -Name "client_qt_import"' in text
    assert 'Add-RunnerFailure "$Description failed with $exitText.' in text


def test_desktop_e2e_runner_preflights_runner_before_backend_work() -> None:
    text = _read("scripts/test_e2e_desktop.ps1")
    check_index = text.index('Invoke-E2ERunnerEnvironmentPreflight -Mode "check"')
    backend_index = text.index("if ($RebuildBackend)")
    assert check_index < backend_index
    assert "[switch]$PreflightRunner = $true" in text


def test_desktop_e2e_runner_loads_isolated_fixture_secrets_when_reusing_backend() -> None:
    text = _read("scripts/test_e2e_desktop.ps1")
    secret_load = text.index("Set-ImmoAppEnvFromBootstrapSecrets -Names $e2eBootstrapNames")
    backend_choice = text.index("if ($RebuildBackend)")
    pytest_launch = text.index('Write-Host "Running native desktop E2E"')

    assert secret_load < backend_choice < pytest_launch
    assert text.count("Set-ImmoAppEnvFromBootstrapSecrets -Names $e2eBootstrapNames") == 1
    assert "[switch]$ResetRunner" in text
    assert "[switch]$SkipRunnerPreflight" in text
    assert "[int]$WarnFreeMemoryGb = 6" in text
    assert "[int]$MinCriticalFreeMemoryGb = 1" in text
    assert "[int]$MinCommitHeadroomGb = 2" in text
    assert "[double]$ApiTimeoutSeconds = 12.0" in text
    assert "WarnFreeMemoryGb = $WarnFreeMemoryGb" in text
    assert "MinCommitHeadroomGb = $MinCommitHeadroomGb" in text
    assert "RequireDocker = ($RebuildBackend -or $EnsureBackend)" in text
    assert "-ResetRunner cannot be combined with -SkipRunnerPreflight." in text


def test_setup_wizard_e2e_uses_verified_front_door_not_direct_backend_url() -> None:
    runner = _read("scripts/test_e2e_desktop.ps1")
    conftest = _read("app/tests/e2e_desktop/conftest.py")
    backend = _read("app/tests/e2e_desktop/backend.py")
    journeys = _read("app/tests/e2e_desktop/test_journeys.py")
    pages = _read("app/tests/e2e_desktop/pages.py")
    release_runner = _read("scripts/run_e2e_release_validation.ps1")

    assert "--e2e-front-door-url" in conftest
    assert "backend.ensure_front_door_ready(value)" in conftest
    assert "X-ImmoApp-Front-Door" in backend
    assert "immoapp_hub_front_door_identity" in backend
    assert "UseHubFrontDoor" in runner
    assert "IMMOAPP_E2E_FRONT_DOOR_URL" in runner
    assert 'COMPOSE_PROFILES = "hub-front-door"' in runner
    assert 'IMMOAPP_BACKEND_HOST_PORT = "18000"' in runner
    assert 'Invoke-DesktopE2E -Suite "nightly" -RebuildBackend' in release_runner
    assert "UseHubFrontDoor = $true" in release_runner
    assert "e2e_front_door_url" in journeys
    assert "connect_manual(e2e_front_door_url)" in journeys
    assert "immoapp_setup_wizard_front_door_e2e_evidence" in journeys
    assert "persisted_client_base_url" in journeys
    assert "front_door_header" in journeys
    assert "connect_manual(e2e_base_url)" not in journeys
    assert "Unexpected setup wizard during a preseeded desktop E2E run" in pages


def test_desktop_e2e_identity_is_mandatory_without_user_bypass() -> None:
    runner = _read("scripts/test_e2e_desktop.ps1")
    conftest = _read("app/tests/e2e_desktop/conftest.py")
    preflight_cli = _read("app/tests/e2e_desktop/preflight_cli.py")

    forbidden_tokens = (
        "VerifyBackendIdentity",
        "e2e-verify-backend-identity",
        "IMMOAPP_E2E_VERIFY_BACKEND_IDENTITY",
        "skip-identity",
        "verify_identity",
    )
    for token in forbidden_tokens:
        assert token not in runner
        assert token not in conftest
        assert token not in preflight_cli

    assert "backend.ensure_backend_ready(value)" in conftest
    assert "backend.ensure_backend_ready(args.base_url, timeout=args.timeout)" in preflight_cli
    assert "Backend identity preflight:" in runner
    preflight_index = runner.index("& $serverPython @preflightCommand")
    pytest_index = runner.index("& $serverPython @pytestCommand")
    assert preflight_index < pytest_index
    assert "Verify backend identity: mandatory" in runner


def test_desktop_e2e_runner_rejects_synced_container_mode_without_sync_code() -> None:
    text = _read("scripts/test_e2e_desktop.ps1")
    assert "[switch]$AllowSyncedContainer" in text
    assert "[switch]$SyncContainers" in text
    assert "Product desktop E2E no longer supports -SyncContainers" in text
    assert "function Sync-E2ECriticalFilesToContainers" not in text
    assert "criticalFiles" not in text
    assert "docker cp" not in text
    assert "--allow-synced-container" not in text
    assert "--e2e-allow-synced-container" not in text
    assert "VerifyBackendIdentity" not in text


def test_installed_hub_manager_runner_serializes_managed_runtime_boundaries() -> None:
    text = _read("scripts/test_installed_hub_manager.ps1")
    first_stop = text.index("-Action stop")
    first_start = text.index("-Action start")
    assert first_stop < first_start
    assert "Wait-InstalledHubManagerFrontDoorStopped" in text[first_stop:first_start]
    assert text.count("Wait-InstalledHubManagerFrontDoorStopped") >= 3


def test_desktop_e2e_launch_uses_bounded_api_timeout_for_cold_backend() -> None:
    runner = _read("scripts/test_e2e_desktop.ps1")
    conftest = _read("app/tests/e2e_desktop/conftest.py")
    runtime = _read("app/tests/e2e_desktop/runtime.py")
    assert "[double]$ApiTimeoutSeconds = 12.0" in runner
    assert "Format-E2EApiTimeoutSeconds -Value $ApiTimeoutSeconds" in runner
    assert "-lt 3 -or $Value -gt 60" in runner
    assert "[Math]::Max(30.0, [double]$apiTimeoutSecondsText)" in runner
    assert "--timeout" in runner
    assert "$backendPreflightTimeoutSecondsText" in runner
    assert "--e2e-api-timeout-seconds" in runner
    assert "--e2e-api-timeout-seconds" in conftest
    assert "validate_api_timeout_seconds(raw)" in conftest
    assert 'env["IMMOAPP_API_TIMEOUT"] = format_api_timeout_seconds' in runtime
    assert 'env.setdefault("IMMOAPP_API_TIMEOUT"' not in runtime


def test_release_validation_wrapper_reuses_runner_and_rebuilds_backend_once_for_nightly() -> None:
    text = _read("scripts/run_e2e_release_validation.ps1")
    assert "reset_e2e_environment.ps1" in text
    assert "test_e2e_desktop.ps1" in text
    assert "[int]$WarnFreeMemoryGb = 6" in text
    assert "[int]$MinCriticalFreeMemoryGb = 1" in text
    assert "[int]$MinCommitHeadroomGb = 2" in text
    assert "[double]$ApiTimeoutSeconds = 12.0" in text
    assert "Format-E2EApiTimeoutSeconds -Value $ApiTimeoutSeconds" in text
    assert "ApiTimeoutSeconds = [double]$apiTimeoutSecondsText" in text
    assert "KillStaleDesktopProcesses = $true" in text
    assert "KillStaleServerProcesses = $true" in text
    assert 'Invoke-DesktopE2E -Suite "smoke"' not in text
    assert 'Invoke-DesktopE2E -Suite "nightly" -RebuildBackend' in text
    assert "IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND" in text
    assert "verify_dependency_vulns.py" in text


def test_host_runtime_endpoints_normalize_postgres_localhost_to_numeric_loopback() -> None:
    text = _read("scripts/common.ps1")
    function_start = text.index("function Set-ImmoAppHostRuntimeEndpoints")
    function_body = text[
        function_start : text.index("function Test-ImmoAppHostWindows", function_start)
    ]
    assert '$env:POSTGRES_HOST -eq "localhost"' in function_body
    assert '$env:POSTGRES_HOST -eq "::1"' in function_body
    assert '$env:POSTGRES_HOST = "127.0.0.1"' in function_body
