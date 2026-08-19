from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_beta_release_checklist_freezes_scope_and_owner_account() -> None:
    text = _read("docs/guides/BETA_RELEASE_CHECKLIST.md")

    for token in (
        "Auth, session, login, and logout.",
        "Offer photos upload, list, view, delete, and re-add.",
        "Import happy path and review-required path.",
        "Contract create, edit, print, sign or cancel, and delete.",
        "Backup and restore drill, including database and object storage.",
        "owner/admin",
        "admin/admin",
        "no dev-only E2E control routes enabled",
    ):
        assert token in text
    assert "DB-only restore is not enough" in text


def test_local_beta_client_guard_resets_owner_and_clears_admin_sessions() -> None:
    text = _read("scripts/prepare_local_beta_client.ps1")

    assert '[string]$BaseUrl = "http://127.0.0.1:8000"' in text
    assert '[string]$Username = "owner"' in text
    assert "$env:IMMOAPP_APPDATA_ROOT = $runtimePaths.AppDataRoot" in text
    assert "Local beta product-flow validation must use owner/admin" in text
    assert "AllowAdmin" in text
    assert '{"admin", "owner", username}' in text
    assert "clear_persisted_session(candidate)" in text
    assert "clear_session_credentials()" in text
    assert "reset_api_session()" in text
    assert "clear_api_token()" in text
    assert "remember_session=remember_session" in text


def test_client_endpoint_script_verifies_front_door_by_default_and_marks_dev_bypass() -> None:
    script = _read("scripts/set_client_api_endpoint.ps1")
    wrapper = _read("scripts/run_beta_release_validation.ps1")

    assert "set_verified_api_config" in script
    assert "DevBypassFrontDoorVerification" in script
    assert "local_dev_unverified" in script
    assert (
        "WARNING: dev/proof-only endpoint configured without Hub front-door verification" in script
    )
    assert "set_api_config(" in script
    assert "if dev_bypass:" in script
    assert "set_verified_api_config(" in script
    assert "evidence cannot use local_dev_unverified endpoint source" in wrapper


def test_dev_stack_is_independent_from_installed_hub_runtime_provider() -> None:
    stack = _read("scripts/stack.ps1")

    assert "function Get-DevDockerInvocationPrefix" in stack
    assert "function Invoke-DevDocker" in stack
    assert "IMMOAPP_DEV_DOCKER_CONTEXT" in stack
    assert '$context = "desktop-linux"' in stack
    assert 'Invoke-DevDocker -DockerArgs (@("compose") + $ComposeArgs)' in stack
    assert "Invoke-ImmoAppHubCompose" not in stack
    assert "Invoke-ImmoAppHubRuntimeCommand" not in stack


def test_dev_stack_uses_explicit_dev_docker_context_behaviorally(tmp_path: Path) -> None:
    appdata_root = tmp_path / "ProgramData" / "ImmoApp"
    config_root = appdata_root / "config"
    config_root.mkdir(parents=True)
    (config_root / "hub_runtime_provider.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_runtime_provider",
                "schema_version": 1,
                "provider_mode": "managed_wsl2_container_runtime_artifact",
                "runtime_dependency_mode": "managed_wsl2_container_runtime_artifact",
                "proof_only": True,
            }
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    docker_args = tmp_path / "docker-args.txt"
    (fake_bin / "docker.cmd").write_text(
        '@echo off\r\n>>"%IMMOAPP_FAKE_DOCKER_ARGS%" echo %*\r\nexit /b 0\r\n',
        encoding="ascii",
    )
    env_file = tmp_path / "dev.env"
    env_file.write_text("COMPOSE_PROFILES=\n", encoding="ascii")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["IMMOAPP_APPDATA_ROOT"] = str(appdata_root)
    env["IMMOAPP_DEV_DOCKER_CONTEXT"] = "phase3-dev-proof"
    env["IMMOAPP_FAKE_DOCKER_ARGS"] = str(docker_args)
    env.pop("DOCKER_CONTEXT", None)
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "stack.ps1"),
            "-Action",
            "ps",
            "-EnvFile",
            str(env_file),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    invoked = docker_args.read_text(encoding="utf-8")
    assert "--context phase3-dev-proof compose" in invoked
    assert " ps" in invoked


def test_live_auth_smoke_does_not_depend_on_openbao_runtime_state() -> None:
    smoke = _read("scripts/check_live_auth_smoke.py")

    assert "def _configure_isolated_smoke_secrets" in smoke
    assert 'env["IMMOAPP_SECRETS_BACKEND"] = "env"' in smoke
    assert 'env["IMMOAPP_ALLOW_ENV_SECRETS"] = "1"' in smoke
    assert 'env["IMMOAPP_SECRETS_REQUIRED"] = "0"' in smoke
    assert 'env["IMMOAPP_SECRETS_OVERWRITE"] = "0"' in smoke
    assert 'env["IMMOAPP_SKIP_CELERY_APP"] = "1"' in smoke


def test_live_auth_smoke_secret_isolation_is_behavioral() -> None:
    smoke = cast(Any, importlib.import_module("scripts.check_live_auth_smoke"))
    env = {
        "IMMOAPP_SECRETS_BACKEND": "openbao",
        "IMMOAPP_ALLOW_ENV_SECRETS": "0",
        "IMMOAPP_SECRETS_REQUIRED": "1",
        "IMMOAPP_SECRETS_OVERWRITE": "1",
        "IMMOAPP_SKIP_CELERY_APP": "0",
    }

    smoke._configure_isolated_smoke_secrets(env)

    assert env["IMMOAPP_SECRETS_BACKEND"] == "env"
    assert env["IMMOAPP_ALLOW_ENV_SECRETS"] == "1"
    assert env["IMMOAPP_SECRETS_REQUIRED"] == "0"
    assert env["IMMOAPP_SECRETS_OVERWRITE"] == "0"
    assert env["IMMOAPP_SKIP_CELERY_APP"] == "1"


def test_installer_packaging_is_deterministic_and_installer_exe_based() -> None:
    requirements = _read("requirements/packaging.txt")
    build = _read("scripts/build_desktop_installer.ps1")
    installer = _read("deployment/installer/ImmoAppBeta.iss")

    assert "pyinstaller==6.20.0" in requirements
    assert "[switch]$WhatIfToolCheckOnly" in build
    assert "[string]$GitExe" in build
    assert "[string]$OutputRoot" in build
    assert "GIT_EXE" in build
    assert "INNO_SETUP_ISCC" in build
    assert '[Environment]::GetEnvironmentVariable("INNO_SETUP_ISCC", "User")' in build
    assert '[Environment]::GetEnvironmentVariable("INNO_SETUP_ISCC", "Machine")' in build
    assert 'Join-Path $env:LOCALAPPDATA "Programs\\Inno Setup 6\\ISCC.exe"' in build
    assert "AppData\\Local\\Programs\\Inno Setup 6\\ISCC.exe" in build
    assert "& $resolved --version" in build
    assert '& $Path "/?"' in build
    assert "6\\.7\\.1" not in build
    assert "stable major version 6" in build
    assert '$versionSource = "unreliable_metadata"' in build
    assert "iscc_version_text" in build
    assert "iscc_product_version" in build
    assert "iscc_file_version" in build
    assert "iscc_version_source" in build
    assert "function Resolve-GitCommand" in build
    assert "Git executable not found" in build
    assert "$git -C $repoRoot status --short" in build
    assert "Refusing to build installer from a dirty worktree" in build
    assert "Assert-NoForbiddenBundledFiles" in build
    assert "GetRelativePath" not in build
    assert '$name.EndsWith(".zip") -or' not in build
    assert '$name -match "\\.(zip|7z|tar|gz)$"' in build
    assert '$lower -match "(backup|release|bundle|artifact)"' in build
    assert "Get-FileHash -LiteralPath $installerPath -Algorithm SHA256" in build
    assert "installer_sha256" in build
    assert "source_commit_sha" in build
    assert "Installer tool check passed." in build
    assert "public_installer_name" in build
    assert 'installer_role = "desktop_and_or_hub"' in build
    assert 'installer_role_support = "desktop_and_or_hub"' in build
    assert "supports_desktop_only = $true" in build
    assert "supports_hub_only = $true" in build
    assert "supports_desktop_and_hub = $true" in build
    assert 'installs_office_hub_backend = "when_hub_desktop_role_selected"' in build
    assert "office_hub_role_supported = $true" in build
    assert "installer_signed" in build
    assert "authenticode_status" in build
    assert "internal_build_id" in build
    assert "Resolve-InstallerOutputRoot" in build
    assert "AllowRepoLocalReleaseArtifacts" in build
    assert "C:\\ProgramData\\ImmoApp\\release_artifacts" in build
    assert "Stable release artifacts must use C:\\ProgramData\\ImmoApp\\release_artifacts" in build
    assert 'Join-Path $repoRoot "dist"' not in build
    assert '"--windowed"' in build
    assert '"--onedir"' in build
    assert '"--collect-all", "PySide6"' not in build
    assert '"--hidden-import", "PySide6.QtWebSockets"' in build
    assert '"--add-data", "$identityPath;app"' in build
    assert '"--add-data", "$installerIdentityPath;app"' in build
    assert "immoapp_installer_build_identity" in build
    assert "desktop_client_only = $false" in build
    assert "office_hub_role_supported = $true" in build
    assert '"--specpath", $buildRoot' in build
    for module in ("app.tests", "tests", "scripts", "server", "deployment", "docs"):
        assert f'"--exclude-module", "{module}"' in build
    assert "Get-DesktopBundleForbiddenMatches" in build
    assert "New-DesktopBundleInventory" in build
    assert "Copy-HubInstallerPayload" in build
    assert "Get-InstallerHubPayloadFiles" in build
    assert "immoapp_installer_package_inventory" in build
    assert "PyInstaller Hub Manager bundle" in build
    assert "app\\hub_manager_app.py" in build
    assert "ImmoApp Hub Manager.exe" in build
    assert "$hubManagerDistRoot" in build
    assert "Hub Manager launcher was not copied into installer bundle root." in build
    assert 'installer_role_support = "desktop_and_or_hub"' in build
    assert "forbidden_path_matches" in build
    assert "required_file_checks" in build
    assert "detected_forbidden_paths" in build
    assert "forbidden_policy" in build
    assert "bundle_inventory_path" in build
    assert "bundle_inventory_sha256" in build
    assert "package_inventory_path" in build
    assert "package_inventory_sha256" in build
    assert "installer_identity_bundle_inventory_sha256" in build
    assert "bundle_inventory_file_count" in build
    assert "bundle_inventory_total_byte_size" in build
    assert "[switch]$KeepPyInstallerOutput" in build
    assert "[switch]$InspectBundleOnly" in build
    for segment in (
        '".git"',
        '".tmp"',
        '"tests"',
        '"server"',
        '"unapproved scripts"',
        '"unapproved deployment files"',
        '"docs"',
        '"__pycache__"',
    ):
        assert segment in build
    for bundled in (
        "scripts/setup_office_hub.ps1",
        "scripts/hub_manager.ps1",
        "ImmoApp Hub Manager.exe",
        "scripts/common.ps1",
        "scripts/register_managed_hub_runtime_provider.ps1",
        "scripts/uninstall_managed_hub_runtime_provider.ps1",
        "scripts/bootstrap_managed_wsl2_runtime.ps1",
        "scripts/hub_runtime_profile.py",
        "core/__init__.py",
        "core/env_files.py",
        "core/env_flags.py",
        "core/paths.py",
        "core/models_audit.py",
        "core/runtime/__init__.py",
        "core/runtime/hub_runtime_profile.py",
        "deployment/env/.env.example",
        "deployment/managed-runtime/rootfs/ImmoAppRuntime.rootfs.tar",
        "deployment/managed-runtime/images/immoapp-runtime-images.tar",
        "deployment/managed-runtime/config/managed_wsl2_runtime_rootfs_inventory.json",
        "deployment/managed-runtime/config/managed_wsl2_runtime_image_bundle_inventory.json",
        "deployment/managed-runtime/config/managed_wsl2_runtime_artifact_inventory.json",
        "deployment/managed-runtime/artifact/managed-wsl2-artifact/bin/immoapp-managed-wsl2-bridge.ps1",
        "deployment/managed-runtime/artifact/managed-wsl2-artifact/bin/backup-managed-hub.ps1",
    ):
        assert bundled in build
    hub_payload_block = build.split("function Get-InstallerHubPayloadFiles", 1)[1].split(
        "function Test-InstallerHubPayloadPathAllowed", 1
    )[0]
    for forbidden in (
        "scripts/build_managed_wsl2_runtime_artifact.ps1",
        "scripts/build_managed_wsl2_runtime_rootfs.ps1",
        "scripts/build_managed_wsl2_runtime_image_bundle.ps1",
        "scripts/stack.ps1",
        "scripts/backup_release_bundle.ps1",
        "scripts/verify_release_backup_integrity.py",
        "scripts/verify_release_bundle_manifest.py",
        "deployment/compose/compose.yml",
        "deployment/compose/compose.windows.yml",
        "deployment/compose/compose.app.yml",
        "deployment/proxy/Caddyfile",
        "deployment/managed-runtime/bin/start-managed-hub",
        "deployment/managed-runtime/compose/compose.yaml",
    ):
        assert forbidden not in hub_payload_block
    assert "ImmoApp-Beta-$Version-Setup" in build
    assert "ImmoAppBetaSetup-$Version-$gitSha" not in build
    assert "[Setup]" in installer
    assert '#define MyHubManagerExeName "ImmoApp Hub Manager.exe"' in installer
    assert "OutputBaseFilename={#MyAppOutputBase}" in installer
    assert "DefaultDirName={localappdata}\\Programs\\ImmoApp Beta" in installer
    assert (
        "No Flags: unchecked here: Inno checks this Desktop shortcut task initially by default."
        in installer
    )
    desktop_task_line = next(
        line for line in installer.splitlines() if line.startswith('Name: "desktopicon";')
    )
    assert 'Description: "Create a desktop shortcut"' in desktop_task_line
    assert "Flags: unchecked" not in desktop_task_line
    assert (
        'Name: "{autodesktop}\\ImmoApp Beta"; Filename: "{app}\\{#MyAppExeName}"; Tasks: desktopicon; Check: IsDesktopSelected'
        in installer
    )
    assert "Choose what to install" in installer
    assert "Install ImmoApp Desktop" in installer
    assert "Set up this computer as Office Hub" in installer
    assert "Desktop client only" not in installer
    assert "Office Hub + desktop on this computer" not in installer
    assert "HubRolePage.Values[0] := True" in installer
    assert "HubRolePage.Values[1] := False" in installer
    assert "ApplyCommandLineRoleSelection" in installer
    assert "IMMOAPPINSTALLMODE" in installer
    assert "IMMOAPPHUBNAME" in installer
    assert "desktop_only" in installer
    assert "hub_only" in installer
    assert "desktop_and_hub" in installer
    assert "Invalid /IMMOAPPINSTALLMODE" in installer
    assert "Hub installs require /IMMOAPPHUBNAME" in installer
    assert "RaiseException" in installer
    assert "HubRoleSelectOne" in installer
    assert "wpSelectTasks" in installer
    assert "Result := not IsDesktopSelected()" in installer
    assert "CreateInputOptionPage" in installer
    assert "False," in installer
    assert "IsDesktopSelected" in installer
    assert "IsHubSelected" in installer
    assert "Name this office Hub" in installer
    assert "Example: Main Office" in installer
    assert "Choose a simple name your team will recognize" in installer
    assert "CreateInputQueryPage" in installer
    assert "RunHubDesktopFoundationSetup" in installer
    assert "ShellExec('runas'" in installer
    assert "HubSetupFinishLater" in installer
    assert "if not WizardSilent() then begin" in installer
    assert "if WizardSilent() then begin" in installer
    assert "WriteHubSetupDeferredEvidence(EvidencePath, CurrentSetupRunId)" in installer
    assert "silent_install_defers_elevated_hub_setup" in installer
    assert '"setup_deferred":true' in installer
    silent_branch = installer.split("if WizardSilent() then begin", 1)[1].split(
        "SetupLaunched := ShellExec('runas'",
        1,
    )[0]
    assert "WriteHubSetupDeferredEvidence(EvidencePath, CurrentSetupRunId)" in silent_branch
    assert "exit;" in silent_branch
    assert "Office Hub setup was not completed" in installer
    assert "Finish ImmoApp Office Hub Setup" in installer
    assert "hub_setup_launch_requested" in installer
    assert "HubSetupEvidenceAppliedGo" in installer
    assert "setup_run_id" in installer
    assert "CurrentSetupRunId := NewSetupRunId()" in installer
    assert "Random(" not in installer
    assert "DeleteFile(EvidencePath)" in installer
    assert "JsonContainsStringField(JsonText, 'setup_run_id', SetupRunId)" in installer
    assert "JsonContainsStringField(JsonText, 'proof_result', 'GO')" in installer
    assert "JsonContainsBooleanField(JsonText, 'selected_install_hub', True)" in installer
    assert "JsonContainsStringField(JsonText, 'install_mode', 'hub_only')" in installer
    assert "JsonContainsStringField(JsonText, 'install_mode', 'desktop_and_hub')" in installer
    assert "JsonContainsBooleanField(JsonText, 'elevated_setup_observed', True)" in installer
    assert "JsonContainsBooleanField(JsonText, 'lan_access_enabled', True)" in installer
    assert (
        "JsonContainsStringField(JsonText, 'firewall_status', 'skipped_local_only')"
        not in installer
    )
    assert "JsonContainsStringField(JsonText, 'local_port', '8000')" in installer
    assert "Pos('\"go\"'" not in installer
    assert "GetSelectedHubSetupRole" in installer
    assert "Result := 'HubOnly'" in installer
    assert "' -Role ' + GetSelectedHubSetupRole()" in installer
    assert "-SetupRunId" in installer
    assert "-CreateFirewallRule -NoAutoStart -NoStartHub" in installer
    assert "-ValidateOnly" not in installer
    for shortcut in (
        "ImmoApp Hub Manager",
        "Finish ImmoApp Office Hub Setup",
        "ImmoApp Hub Status",
        "ImmoApp Hub Connection Details",
        "ImmoApp Hub Runtime Status",
        "ImmoApp Hub Firewall Status",
        "Copy ImmoApp Hub Connection URL",
        "Backup ImmoApp Hub Now",
        "Collect ImmoApp Support Bundle",
        "Open ImmoApp Hub Logs",
    ):
        assert shortcut in installer
    hub_shortcut_lines = [
        line
        for line in installer.splitlines()
        if line.startswith('Name: "{autoprograms}\\ImmoApp Hub\\')
    ]
    assert hub_shortcut_lines
    assert all('Filename: "{app}\\{#MyHubManagerExeName}"' in line for line in hub_shortcut_lines)
    assert all("WindowsPowerShell" not in line for line in hub_shortcut_lines)
    assert "--action start" in installer
    assert "--action finish-hub-setup" in installer
    assert 'Open ImmoApp Desktop";' in installer
    assert "Check: IsHubAndDesktopSelected" in installer
    assert "Rename-Computer" not in installer
    assert "Set-ComputerName" not in installer
    assert "[Files]" in installer
    assert "[InstallDelete]" in installer
    for generated_leftover_cleanup in (
        r'Type: filesandordirs; Name: "{app}\core\__pycache__"',
        r'Type: filesandordirs; Name: "{app}\core\runtime\__pycache__"',
        r'Type: files; Name: "{app}\core\*.pyc"',
        r'Type: files; Name: "{app}\core\runtime\*.pyc"',
        r'Type: files; Name: "{app}\is-*.tmp"',
        r'Type: files; Name: "{app}\deployment\managed-runtime\images\is-*.tmp"',
    ):
        assert generated_leftover_cleanup in installer
    assert "procedure DeleteInstallerTempFiles(Directory: String);" in installer
    assert "AddBackslash(Directory) + 'is-*.tmp'" in installer
    assert "DeleteInstallerTempFiles(ExpandConstant('{app}'));" in installer
    assert "CleanInstallRootGeneratedLeftovers();" in installer
    for obsolete_builder in (
        r'Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_artifact.ps1"',
        r'Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_rootfs.ps1"',
        r'Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_image_bundle.ps1"',
    ):
        assert obsolete_builder in installer


def _write_release_artifact_fixture(
    root: Path,
    *,
    commit_sha: str = "a" * 40,
    include_summary: bool = True,
    include_inventory: bool = True,
    include_hub_manager: bool = True,
    summary_sha_override: str | None = None,
    summary_commit_override: str | None = None,
) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    installer = root / "ImmoApp-Beta-1.0.0-Setup.exe"
    installer.write_bytes(b"installer-bytes")
    inventory = root / "ImmoApp-Beta-1.0.0-Setup.bundle_inventory.json"
    summary = root / "ImmoApp-Beta-1.0.0-Setup.summary.json"
    files = [
        {
            "relative_path": "ImmoApp.exe",
            "category": "desktop_runtime",
            "sha256": "1" * 64,
            "bytes": 1,
        }
    ]
    required = [{"relative_path": "ImmoApp.exe", "category": "desktop_runtime", "present": True}]
    if include_hub_manager:
        files.append(
            {
                "relative_path": "ImmoApp Hub Manager.exe",
                "category": "hub_manager",
                "sha256": "2" * 64,
                "bytes": 1,
            }
        )
        required.append(
            {
                "relative_path": "ImmoApp Hub Manager.exe",
                "category": "hub_manager",
                "present": True,
            }
        )
    inventory_payload = {
        "kind": "immoapp_installer_package_inventory",
        "schema_version": 1,
        "source_commit_sha": commit_sha,
        "proof_result": "GO",
        "installer_role_support": "desktop_and_or_hub",
        "supports_desktop_only": True,
        "supports_hub_only": True,
        "supports_desktop_and_hub": True,
        "forbidden_path_matches": [],
        "detected_forbidden_paths": [],
        "missing_required_file_checks": [],
        "required_file_checks": required,
        "files": files,
        "file_count": len(files),
        "total_file_count": len(files),
        "total_bytes": 2,
        "total_byte_size": 2,
    }
    if include_inventory:
        inventory.write_text(json.dumps(inventory_payload), encoding="utf-8")
    if include_summary:
        inventory_sha = _sha(inventory) if inventory.exists() else "0" * 64
        summary_payload = {
            "kind": "immoapp_desktop_installer_build_summary",
            "source_commit_sha": summary_commit_override or commit_sha,
            "source_worktree_clean": True,
            "installer_role_support": "desktop_and_or_hub",
            "supports_desktop_only": True,
            "supports_hub_only": True,
            "supports_desktop_and_hub": True,
            "installer_path": str(installer),
            "installer_sha256": summary_sha_override or _sha(installer),
            "bundle_inventory_path": str(inventory),
            "bundle_inventory_sha256": inventory_sha,
            "package_inventory_path": str(inventory),
            "package_inventory_sha256": inventory_sha,
        }
        summary.write_text(json.dumps(summary_payload), encoding="utf-8")
    return {"installer": installer, "inventory": inventory, "summary": summary}


def _run_resolver(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "resolve_release_installer_artifact.ps1"),
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_artifact_resolver_selects_valid_hub_manager_artifact(tmp_path: Path) -> None:
    commit = "a" * 40
    artifact = tmp_path / "release" / commit[:12] / "valid"
    paths = _write_release_artifact_fixture(artifact, commit_sha=commit)

    result = _run_resolver("-ArtifactRoot", str(artifact), "-CommitSha", commit)

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["proof_result"] == "GO"
    assert payload["selected_artifact"]["installer_path"] == str(paths["installer"])
    assert payload["selected_artifact"]["hub_manager_packaged_status"] == "GO"


@pytest.mark.parametrize(
    ("fixture_kwargs", "reason"),
    [
        (
            {"include_summary": False, "include_inventory": False},
            "release_artifact_summary_missing_or_ambiguous",
        ),
        ({"include_inventory": False}, "release_artifact_inventory_missing_or_ambiguous"),
        (
            {"summary_sha_override": "0" * 64},
            "Build summary installer_sha256 does not match actual installer hash",
        ),
        ({"summary_commit_override": "b" * 40}, "source_commit_sha does not match expected commit"),
        ({"include_hub_manager": False}, "ImmoApp Hub Manager.exe"),
    ],
)
def test_release_artifact_resolver_rejects_incomplete_or_mismatched_artifacts(
    tmp_path: Path, fixture_kwargs: dict[str, Any], reason: str
) -> None:
    commit = "a" * 40
    artifact = tmp_path / "release" / commit[:12] / "bad"
    _write_release_artifact_fixture(artifact, commit_sha=commit, **fixture_kwargs)

    result = _run_resolver("-ArtifactRoot", str(artifact), "-CommitSha", commit)

    assert result.returncode != 0
    assert reason in (result.stdout + result.stderr)


def _run_self_signed_validation(evidence: Path, installer: Path, sha: str, commit: str) -> str:
    wrapper = REPO_ROOT / "scripts" / "run_beta_release_validation.ps1"
    common = REPO_ROOT / "scripts" / "common.ps1"
    command = f"""
    . '{common}'
    $source = Get-Content -LiteralPath '{wrapper}' -Raw
    $prefix = $source.Substring(0, $source.IndexOf('$repoRoot ='))
    $prefix = $prefix -replace '\\. \\(Join-Path \\$PSScriptRoot "common\\.ps1"\\)', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppSecurityEnv\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Import-ImmoAppEnvFile\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppHostRuntimeEndpoints\\r?\\n', ''
    . ([scriptblock]::Create($prefix))
    Assert-SelfSignedInstallerSignatureEvidence -Path '{evidence}' -ExpectedSourceInstallerPath '{installer}' -ExpectedUnsignedSha256 '{sha}' -ExpectedCommitSha '{commit}' | ConvertTo-Json -Depth 8
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def test_self_signed_validation_rejects_wrong_signer_before_public_trust(tmp_path: Path) -> None:
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"installer")
    evidence = tmp_path / "bad-signer.json"
    commit = "a" * 40
    evidence.write_text(
        json.dumps(
            {
                "kind": "immoapp_installer_self_signed_signature_evidence",
                "proof_result": "GO",
                "signature_type": "self_signed_local_internal",
                "local_internal_signed_status": "GO",
                "public_beta_distribution_status": "NO-GO self-signed local/internal only",
                "signer_subject": "CN=Someone Else",
                "source_commit_sha": commit,
                "source_installer_path": str(installer),
                "unsigned_installer_sha256": _sha(installer),
            }
        ),
        encoding="utf-8",
    )

    output = _run_self_signed_validation(evidence, installer, _sha(installer), commit)

    assert "signer_subject must include Yacine Larbaoui" in output


def test_self_signed_validation_rejects_public_beta_go_claim(tmp_path: Path) -> None:
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"installer")
    evidence = tmp_path / "public-go.json"
    commit = "a" * 40
    evidence.write_text(
        json.dumps(
            {
                "kind": "immoapp_installer_self_signed_signature_evidence",
                "proof_result": "GO",
                "signature_type": "self_signed_local_internal",
                "local_internal_signed_status": "GO",
                "public_beta_distribution_status": "GO",
                "signer_subject": "CN=Yacine Larbaoui",
                "source_commit_sha": commit,
                "source_installer_path": str(installer),
                "unsigned_installer_sha256": _sha(installer),
            }
        ),
        encoding="utf-8",
    )

    output = _run_self_signed_validation(evidence, installer, _sha(installer), commit)

    assert "cannot claim public beta GO" in output


def test_runtime_readiness_summary_keeps_artifact_only_proof_separate(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    config = programdata / "config"
    logs = programdata / "logs"
    config.mkdir(parents=True)
    logs.mkdir(parents=True)
    for name, kind in (
        (
            "managed_wsl2_runtime_artifact_inventory.json",
            "immoapp_managed_wsl2_runtime_artifact_inventory",
        ),
        (
            "managed_wsl2_runtime_image_bundle_inventory.json",
            "immoapp_managed_wsl2_runtime_image_bundle_inventory",
        ),
        (
            "managed_wsl2_runtime_rootfs_inventory.json",
            "immoapp_managed_wsl2_runtime_rootfs_inventory",
        ),
    ):
        (config / name).write_text(
            json.dumps({"kind": kind, "proof_result": "GO", "reason_code": "test_go"}),
            encoding="utf-8",
        )
    (config / "hub_runtime_provider.json").write_text(
        json.dumps({"runtime_dependency_mode": "managed_wsl2_container_runtime_artifact"}),
        encoding="utf-8",
    )
    detection = tmp_path / "detection.json"
    detection.write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_runtime_detection",
                "runtime_start_status": "NO-GO",
                "front_door_health_status": "NO-GO",
                "agency_install_status": "NO_GO",
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "collect_hub_runtime_readiness_summary.ps1"),
            "-RuntimeDetectionJson",
            str(detection),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["runtime_artifact_status"] == "GO"
    assert payload["image_bundle_status"] == "GO"
    assert payload["rootfs_status"] == "GO"
    assert payload["provider_registration_status"] == "GO"
    assert payload["runtime_start_status"] == "NO-GO"
    assert payload["front_door_health_status"] == "NO-GO"
    assert payload["public_beta_status"] == "NO_GO"


def test_release_backup_restore_requires_object_mirror_and_verification() -> None:
    backup = _read("scripts/backup_release_bundle.ps1")
    restore = _read("scripts/restore_release_bundle.ps1")
    verifier = _read("scripts/verify_release_restore_bundle.py")
    integrity = _read("scripts/verify_release_backup_integrity.py")
    manifest = _read("scripts/verify_release_bundle_manifest.py")
    repair_ps1 = _read("scripts/repair_local_dev_release_integrity.ps1")
    repair_py = _read("scripts/repair_local_dev_release_integrity.py")
    runbook = _read("ops/runbooks/RESTORE_DRILL_RUNBOOK.md")

    assert "verify_release_backup_integrity.py" in backup
    assert (
        "Release backup refused: database integrity check failed. Run explicit local-dev repair/reset or fix production data first."
        in backup
    )
    assert "repair_local_dev_release_integrity" not in backup
    assert "Set-ImmoAppHubRuntimeProfileEnv" in backup
    assert backup.index("Set-ImmoAppHubRuntimeProfileEnv") < backup.index(
        "Set-ImmoAppHostRuntimeEndpoints"
    )
    assert "Set-ImmoAppHubRuntimeProfileEnv" in restore
    assert restore.index("Set-ImmoAppHubRuntimeProfileEnv") < restore.index(
        "Set-ImmoAppHostRuntimeEndpoints"
    )
    assert "pg_dump" in backup
    assert "Get-Command pg_dump" in backup
    assert "docker cp" in backup
    assert "Quote-ShSingle" in backup
    assert "Release backup refused: bundle work directory already exists" in backup
    assert '".rb_"' in backup
    assert "manifest.json" in backup
    assert "sha256" in backup
    assert 'report = "integrity/release_backup_integrity.json"' in backup
    assert "accounts_user" in integrity
    assert "task_failures.agency_id" in integrity
    assert "locations p WHERE p.location_id = t.location_id" in integrity
    assert "imports_importchunkphase" in integrity
    assert "imports_importagencyprofile" in integrity
    assert "custom_locations.agency_id" in integrity
    assert "storage_objects.ready_object_bytes" in integrity
    assert "status = 'ready'" in integrity
    assert "UPDATE auth_security_events" not in integrity
    assert "pg_restore" in restore
    assert "Get-Command psql" in restore
    assert "Get-Command pg_restore" in restore
    assert "docker cp restore dump" in restore
    assert "verify_release_bundle_manifest.py" in restore
    assert "New-RestoreBucketName" in restore
    assert "Object restore cannot be skipped for beta release proof." in restore
    assert "Assert-RestoreDatabaseName" in restore
    assert "Quote-SqlIdentifier" in restore
    assert "Quote-ShSingle" in restore
    assert "/backup/$mirrorRootRelative release/$restoreBucket" not in restore
    assert "mc mirror --overwrite /backup/minio/$bucket release/$bucket" not in restore
    assert "IMMOAPP_RESTORE_BUCKET_OVERRIDE" in restore
    assert "Assert-RestoreDrillBucketName" in restore
    assert "verify_release_restore_bundle.py --bundle-path" in restore
    assert 'manifest.get("kind") != "immoapp_release_backup_bundle"' in manifest
    assert "database/immoapp.dump" in manifest
    assert "integrity/release_backup_integrity.json" in manifest
    assert "PurePosixPath" in manifest
    assert "ParsedManifest" in manifest
    assert "duplicate member names" in manifest
    assert "unlisted payload file" in manifest
    assert "Extraction target must be empty" in manifest
    assert "Extraction target parent is a symlink" in manifest
    assert "Extraction target escapes root" in manifest
    assert "extracting-" in manifest
    assert "_promote_staging" in manifest
    assert 'parser.add_argument("--apply", action="store_true")' in repair_py
    assert (
        'parser.add_argument("--confirm-disposable-local-data", action="store_true")' in repair_py
    )
    assert "IMMOAPP_PROD_CONFIG_STRICT" in repair_py
    assert "allow-non-default-local-database" in repair_py
    assert "db_name=" in repair_py
    assert '"staging"' in repair_py
    assert "Refusing local-dev repair for non-local DB host" in repair_py
    assert "with conn.transaction()" in repair_py
    assert "imports_importagencyprofile.delete_missing_agency" in repair_py
    assert "task_failures.delete_missing_agency" in repair_py
    assert "custom_locations.delete_missing_agency" in repair_py
    assert "storage_objects.soft_delete_missing_ready_bytes" in repair_py
    assert "[switch]$ConfirmDisposableLocalData" in repair_ps1
    assert "[switch]$Apply" in repair_ps1
    assert "[switch]$AllowNonDefaultLocalDatabase" in repair_ps1
    assert "get_object(Bucket=bucket, Key=key)" in verifier
    assert "storage_objects_hash_verified" in verifier
    assert "status = 'ready'" in verifier
    assert "IMMOAPP_RESTORE_BUCKET_OVERRIDE" in verifier
    assert '"contracts"' in verifier
    assert '"imports_importjob"' in verifier
    assert "database-only restore evidence is" in runbook
    assert "missing photo objects as a beta blocker" in runbook
    assert "isolated" in runbook.lower()


def test_release_critical_test_cleanup_covers_known_orphan_tables() -> None:
    e2e_cleanup = _read("app/tests/e2e_desktop/backend.py")
    integration_cleanup = _read("app/tests/server_tests/_integration_auth_helpers.py")
    cleanup_callers = (
        "app/tests/server_tests/test_api_cross_tenant_breach.py",
        "app/tests/server_tests/test_idempotency_concurrency_race.py",
        "app/tests/server_tests/test_idempotency_replay.py",
        "app/tests/server_tests/test_import_asymmetric_entities_integration.py",
        "app/tests/server_tests/test_import_batch_writer_contract.py",
        "app/tests/server_tests/test_import_child_batch_write_integration.py",
        "app/tests/server_tests/test_match_artifact_pipeline_integration.py",
        "app/tests/server_tests/test_match_query_cte_postgres_integration.py",
        "app/tests/server_tests/test_offer_photos_server_contract.py",
        "app/tests/server_tests/test_rls_breach_matrix.py",
        "app/tests/server_tests/test_row_version_cas_runtime.py",
        "app/tests/server_tests/test_storage_lifecycle_integration.py",
        "app/tests/server_tests/test_surface_cache_generation_contract.py",
        "app/tests/server_tests/test_sync_endpoints_integration.py",
    )

    assert "GREATEST(" in integration_cleanup
    assert 'sequence_name = "accounts_agency_id_seq"' in integration_cleanup
    assert 'sequence_name = "accounts_user_id_seq"' in integration_cleanup
    assert "(SELECT last_value FROM {sequence_name})" in integration_cleanup

    for cleanup_source in (e2e_cleanup, integration_cleanup):
        assert "DELETE FROM demande_locations WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM offer_locations WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM match_counts_cache WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM task_failures WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM surface_cache_generation WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM custom_locations WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM api_idempotency_records" in cleanup_source
        assert "DELETE FROM notification_reads" in cleanup_source
        assert "DELETE FROM notifications WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM accounts_userinvite WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM imports_importworkflowstate" in cleanup_source
        assert "DELETE FROM imports_importchunkphase" in cleanup_source
        assert "DELETE FROM imports_importagencyprofile WHERE agency_id = %s" in cleanup_source
        assert "DELETE FROM auth_security_events" in cleanup_source
        assert "WHERE job_id IN" in cleanup_source

    for relative_path in cleanup_callers:
        source = _read(relative_path)
        assert "cleanup_import_test_agency" in source


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_bundle_dir(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    (root / "database").mkdir(parents=True)
    (root / "integrity").mkdir(parents=True)
    (root / "minio" / "immoapp").mkdir(parents=True)
    files = {
        "database/immoapp.dump": b"dump-bytes",
        "integrity/release_backup_integrity.json": b'{"ok": true}',
        "minio/immoapp/object.bin": b"object-bytes",
    }
    entries = []
    for rel, data in files.items():
        path = root / Path(*rel.split("/"))
        path.write_bytes(data)
        entries.append({"path": rel, "bytes": len(data), "sha256": _sha(path)})
    manifest = {
        "kind": "immoapp_release_backup_bundle",
        "database": {"dump": "database/immoapp.dump"},
        "object_storage": {"bucket": "immoapp", "mirror_root": "minio/immoapp"},
        "integrity": {"report": "integrity/release_backup_integrity.json"},
        "files": entries,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_release_manifest_verifier_accepts_valid_dir_and_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)

    assert verifier.verify_bundle(bundle)["kind"] == "immoapp_release_backup_bundle"

    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
    extract_to = tmp_path / "extract"
    verifier.safe_extract(zip_path, extract_to)
    assert (extract_to / "database" / "immoapp.dump").read_bytes() == b"dump-bytes"


def test_release_manifest_extracts_valid_zip_to_missing_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
    extract_to = tmp_path / "missing_extract"

    verifier.safe_extract(zip_path, extract_to)

    assert (extract_to / "manifest.json").is_file()
    assert (extract_to / "minio" / "immoapp" / "object.bin").read_bytes() == b"object-bytes"


def test_release_manifest_extracts_valid_zip_to_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
    extract_to = tmp_path / "empty_extract"
    extract_to.mkdir()

    verifier.safe_extract(zip_path, extract_to)

    assert (extract_to / "database" / "immoapp.dump").read_bytes() == b"dump-bytes"


def test_release_manifest_refuses_non_empty_extract_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    extract_to = tmp_path / "extract"
    extract_to.mkdir()
    (extract_to / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(verifier.ManifestError, match="must be empty"):
        verifier.safe_extract(bundle, extract_to)

    assert not (extract_to / "database").exists()


def test_release_manifest_refuses_symlink_extract_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    extract_to = tmp_path / "extract"
    extract_to.mkdir()
    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        if path == extract_to:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(verifier.ManifestError, match="symlink"):
        verifier.safe_extract(bundle, extract_to)

    assert not (extract_to / "manifest.json").exists()


def test_release_manifest_refuses_unsafe_zip_path_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    zip_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
        archive.writestr("../evil.bin", b"bad")
    extract_to = tmp_path / "extract"

    with pytest.raises(verifier.ManifestError, match="Unsafe traversal"):
        verifier.safe_extract(zip_path, extract_to)

    assert not extract_to.exists()


def test_release_manifest_failed_extraction_leaves_no_partial_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    _set_manifest_entry(bundle, "minio/immoapp/object.bin", "sha256", "0" * 64)
    extract_to = tmp_path / "extract"

    with pytest.raises(verifier.ManifestError, match="SHA-256 mismatch"):
        verifier.safe_extract(bundle, extract_to)

    assert not extract_to.exists()


def test_release_manifest_file_write_failure_keeps_final_absent_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
    calls = 0
    original_write = verifier._write_extracted_file

    def fail_after_first(root: Path, relative_path: str, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("simulated write failure")
        original_write(root, relative_path, data)

    monkeypatch.setattr(verifier, "_write_extracted_file", fail_after_first)
    extract_to = tmp_path / "extract"

    with pytest.raises(OSError, match="simulated write failure"):
        verifier.safe_extract(zip_path, extract_to)

    assert not extract_to.exists()
    assert not list(tmp_path.glob(".extract.extracting-*"))


def test_release_manifest_file_write_failure_keeps_existing_final_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    extract_to = tmp_path / "extract"
    extract_to.mkdir()

    monkeypatch.setattr(
        verifier,
        "_write_extracted_file",
        lambda root, relative_path, data: (_ for _ in ()).throw(OSError("boom")),
    )

    with pytest.raises(OSError, match="boom"):
        verifier.safe_extract(bundle, extract_to)

    assert extract_to.is_dir()
    assert list(extract_to.iterdir()) == []
    assert not list(tmp_path.glob(".extract.extracting-*"))


def test_release_manifest_refuses_symlink_parent_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    parent = tmp_path / "parent"
    extract_to = parent / "extract"
    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        if path == parent:
            return True
        return original_is_symlink(path)

    parent.mkdir()
    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(verifier.ManifestError, match="symlink"):
        verifier.safe_extract(bundle, extract_to)

    assert not extract_to.exists()


def test_release_manifest_verifier_rejects_duplicate_zip_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    zip_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
        archive.writestr("database/immoapp.dump", b"duplicate")

    with pytest.raises(verifier.ManifestError, match="duplicate member names"):
        verifier.verify_bundle(zip_path)


@pytest.mark.parametrize("payload", ("unlisted.bin", "minio/immoapp/extra.bin"))
def test_release_manifest_verifier_rejects_unlisted_dir_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    extra = bundle / Path(*payload.split("/"))
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"extra")

    with pytest.raises(verifier.ManifestError, match="unlisted payload file"):
        verifier.verify_bundle(bundle)


def test_release_manifest_verifier_rejects_unlisted_zip_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    zip_path = tmp_path / "unlisted.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
        archive.writestr("minio/immoapp/unlisted.bin", b"extra")

    with pytest.raises(verifier.ManifestError, match="unlisted payload file"):
        verifier.verify_bundle(zip_path)


def test_release_manifest_verifier_rejects_unsafe_archive_member_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    zip_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
        archive.writestr("../evil.bin", b"bad")

    with pytest.raises(verifier.ManifestError, match="Unsafe traversal"):
        verifier.verify_bundle(zip_path)


def test_release_manifest_verifier_rejects_invalid_bucket_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    _mutate_manifest(
        bundle,
        lambda data: data["object_storage"].update(
            bucket="bad/bucket",
            mirror_root="minio/bad/bucket",
        ),
    )

    with pytest.raises(verifier.ManifestError, match="Invalid object storage bucket"):
        verifier.verify_bundle(bundle)


class _FakeBody(io.BytesIO):
    pass


class _FakeS3Client:
    def __init__(self, payloads: dict[tuple[str, str], bytes]) -> None:
        self.payloads = payloads

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, int]:
        payload = self.payloads[(Bucket, Key)]
        return {"ContentLength": len(payload)}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, _FakeBody]:
        return {"Body": _FakeBody(self.payloads[(Bucket, Key)])}


def test_release_restore_verifier_hashes_restored_object_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    manifest_verifier = importlib.import_module("verify_release_bundle_manifest")
    restore_verifier = importlib.import_module("verify_release_restore_bundle")
    parsed = manifest_verifier.verify_bundle_manifest(_release_bundle_dir(tmp_path))
    restore_bucket = "immoapp-restore-drill-20260515000000-abcdef12"
    monkeypatch.setenv("IMMOAPP_RESTORE_BUCKET_OVERRIDE", restore_bucket)
    monkeypatch.setattr(
        restore_verifier,
        "_s3_client",
        lambda: _FakeS3Client({(restore_bucket, "object.bin"): b"object-bytes"}),
    )

    mode, verified = restore_verifier._verify_storage_objects(
        [{"id": "s1", "bucket": "immoapp", "object_key": "object.bin"}],
        parsed,
    )

    assert mode == "override"
    assert verified == 1


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        (b"wrong-bytes", "size mismatch"),
        (b"object-bytez", "SHA-256 mismatch"),
    ),
)
def test_release_restore_verifier_rejects_size_or_hash_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    message: str,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    manifest_verifier = importlib.import_module("verify_release_bundle_manifest")
    restore_verifier = importlib.import_module("verify_release_restore_bundle")
    parsed = manifest_verifier.verify_bundle_manifest(_release_bundle_dir(tmp_path))
    restore_bucket = "immoapp-restore-drill-20260515000000-abcdef12"
    monkeypatch.setenv("IMMOAPP_RESTORE_BUCKET_OVERRIDE", restore_bucket)
    monkeypatch.setattr(
        restore_verifier,
        "_s3_client",
        lambda: _FakeS3Client({(restore_bucket, "object.bin"): payload}),
    )

    with pytest.raises(RuntimeError, match=message):
        restore_verifier._verify_storage_objects(
            [{"id": "s1", "bucket": "immoapp", "object_key": "object.bin"}],
            parsed,
        )


def test_release_restore_verifier_rejects_unsafe_object_key_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    manifest_verifier = importlib.import_module("verify_release_bundle_manifest")
    restore_verifier = importlib.import_module("verify_release_restore_bundle")
    parsed = manifest_verifier.verify_bundle_manifest(_release_bundle_dir(tmp_path))
    monkeypatch.setattr(restore_verifier, "_s3_client", lambda: _FakeS3Client({}))

    with pytest.raises(RuntimeError, match="Unsafe storage object key"):
        restore_verifier._verify_storage_objects(
            [{"id": "s1", "bucket": "immoapp", "object_key": "../object.bin"}],
            parsed,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda root: (root / "manifest.json").unlink(), "manifest missing"),
        (
            lambda root: _mutate_manifest(root, lambda data: data.update(kind="wrong")),
            "Unsupported release bundle kind",
        ),
        (
            lambda root: _remove_manifest_path(root, "database/immoapp.dump"),
            "database/immoapp.dump",
        ),
        (
            lambda root: (root / "database" / "immoapp.dump").unlink(),
            "Manifest-listed file missing",
        ),
        (
            lambda root: _remove_manifest_path(root, "integrity/release_backup_integrity.json"),
            "integrity/release_backup_integrity.json",
        ),
        (
            lambda root: _set_manifest_entry(root, "database/immoapp.dump", "sha256", "0" * 64),
            "SHA-256 mismatch",
        ),
        (
            lambda root: _set_manifest_entry(root, "database/immoapp.dump", "bytes", 999),
            "byte size mismatch",
        ),
        (
            lambda root: _set_manifest_entry(
                root, "database/immoapp.dump", "path", "/tmp/immoapp.dump"
            ),
            "Unsafe absolute",
        ),
        (
            lambda root: _set_manifest_entry(
                root, "database/immoapp.dump", "path", "C:/tmp/immoapp.dump"
            ),
            "Unsafe absolute",
        ),
        (
            lambda root: _set_manifest_entry(
                root, "database/immoapp.dump", "path", "../immoapp.dump"
            ),
            "Unsafe traversal",
        ),
        (
            lambda root: _remove_manifest_path(root, "minio/immoapp/object.bin"),
            "MinIO mirror root is missing or empty",
        ),
    ),
)
def test_release_manifest_verifier_rejects_invalid_bundles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[Path], None],
    message: str,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verifier = importlib.import_module("verify_release_bundle_manifest")
    bundle = _release_bundle_dir(tmp_path)
    mutate(bundle)

    with pytest.raises(verifier.ManifestError, match=message):
        verifier.verify_bundle(bundle)


def _mutate_manifest(root: Path, callback: Callable[[dict[str, Any]], None]) -> None:
    path = root / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    callback(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _remove_manifest_path(root: Path, target: str) -> None:
    def _remove(data: dict[str, Any]) -> None:
        data["files"] = [item for item in data["files"] if item["path"] != target]

    _mutate_manifest(root, _remove)


def _set_manifest_entry(root: Path, target: str, key: str, value: object) -> None:
    def _set(data: dict[str, Any]) -> None:
        for item in data["files"]:
            if item["path"] == target:
                item[key] = value
                return
        raise AssertionError(target)

    _mutate_manifest(root, _set)


def test_restore_database_validation_rejects_unsafe_names() -> None:
    script = REPO_ROOT / "scripts" / "restore_release_bundle.ps1"
    command = f"""
    $source = Get-Content -LiteralPath '{script}' -Raw
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {{ throw 'parse failed' }}
    $func = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-RestoreDatabaseName' }}, $true)
    if ($null -eq $func) {{ throw 'function missing' }}
    . ([scriptblock]::Create($func.Extent.Text))
    foreach ($name in @('', 'postgres', 'template0', 'bad-name', 'bad/name', 'bad\\name', 'bad;drop', 'Bad', '1bad')) {{
        try {{
            Assert-RestoreDatabaseName -DatabaseName $name -ConfiguredPrimaryDb 'immoapp'
            throw "accepted $name"
        }} catch {{
            if ($_.Exception.Message -like 'accepted*') {{ throw }}
        }}
    }}
    Assert-RestoreDatabaseName -DatabaseName 'immoapp_restore_drill' -ConfiguredPrimaryDb 'immoapp'
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_touched_powershell_scripts_parse() -> None:
    files = (
        "scripts/build_desktop_installer.ps1",
        "scripts/run_beta_release_validation.ps1",
        "scripts/backup_release_bundle.ps1",
        "scripts/restore_release_bundle.ps1",
        "scripts/repair_local_dev_release_integrity.ps1",
        "scripts/verify_lan_workstation_reachability.ps1",
        "scripts/collect_installed_app_inventory.ps1",
        "scripts/collect_install_lifecycle_evidence.ps1",
        "scripts/collect_installed_desktop_front_door_evidence.ps1",
        "scripts/collect_fresh_machine_install_evidence.ps1",
        "scripts/write_manual_product_proof_evidence.ps1",
        "scripts/collect_lan_workstation_evidence.ps1",
    )
    paths = ", ".join(f"'{(REPO_ROOT / file).as_posix()}'" for file in files)
    command = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            f"foreach ($file in @({paths})) {{",
            "  $tokens = $null; $errors = $null",
            "  [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$errors) > $null",
            "  if ($errors.Count -gt 0) { throw ($errors | Select-Object -First 1).Message }",
            "}",
        )
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_beta_release_validation_wrapper_contract() -> None:
    wrapper = _read("scripts/run_beta_release_validation.ps1")
    e2e_release = _read("scripts/run_e2e_release_validation.ps1")
    stack = _read("scripts/stack.ps1")
    common = _read("scripts/common.ps1")

    assert "Set-StrictMode -Version Latest" in wrapper
    assert (
        '[string]$ReleaseArtifactRoot = "C:\\ProgramData\\ImmoApp\\release_artifacts\\beta"'
        in wrapper
    )
    assert "[switch]$AllowReplaceReleaseArtifacts" in wrapper
    assert "[switch]$CleanPreviousValidationArtifacts" in wrapper
    assert "[string]$HubInstallEvidenceJson" in wrapper
    assert "[string]$HubStatusEvidenceJson" in wrapper
    assert "[string]$InstalledInventoryEvidenceJson" in wrapper
    assert "[string]$InstallLifecycleEvidenceJson" in wrapper
    assert "[string]$SetupWizardFrontDoorE2eEvidenceJson" in wrapper
    assert "[string]$InstalledDesktopFrontDoorEvidenceJson" in wrapper
    assert "[string]$ManualProductProofEvidenceJson" in wrapper
    assert "[string]$DesktopInstallerBuildSummaryJson" in wrapper
    assert "Assert-DesktopInstallerBuildSummary" in wrapper
    assert "installer_path does not exist" in wrapper
    assert (
        'Assert-PathOutsideRepo -RepoRoot $RepoRoot -Path $installerPath -Label "$label installer_path"'
        in wrapper
    )
    assert 'Get-JsonPropertyValue -Data $data -Name "forbidden_path_matches"' in wrapper
    assert 'Get-JsonPropertyValue -Data $data -Name "backend_url"' in wrapper
    assert "$property = $Data.PSObject.Properties[$Name]" in wrapper
    assert "return ,$property.Value" in wrapper
    assert '"installer_sha256_verified"' in wrapper
    assert '"installer_sha256_claimed_only"' in wrapper
    assert '"verified_from_installer_file"' in wrapper
    assert "cannot use claimed-only installer SHA evidence" in wrapper
    for phase in (
        "environment_and_repo_preflight",
        "backup_restore_proof",
        "e2e_repo_gates",
        "installer_build",
        "setup_wizard_front_door_e2e",
        "installed_app_inventory",
        "install_lifecycle",
        "installed_app_front_door_connectivity",
        "full_desktop_installer_release_proof",
        "fresh_machine_install",
        "hub_install",
        "hub_status",
        "lan_hub_workstation",
    ):
        assert phase in wrapper
    assert "summary.json" in wrapper
    assert "summary.txt" in wrapper
    assert "ConvertTo-Json -Depth 10" in wrapper
    assert "Join-WindowsProcessArguments" in wrapper
    assert "Start-Process -FilePath $Command" not in wrapper
    assert "& $Command @Arguments 1> $stdoutPath 2> $stderrPath" in wrapper
    assert '$ErrorActionPreference = "Continue"' in wrapper
    assert "$nativeInvokeErrorActionPreference = $ErrorActionPreference" in wrapper
    assert "$exitCode = $LASTEXITCODE" in wrapper
    assert "*>&1 | Tee-Object" not in wrapper
    assert "docker_service_status" in wrapper
    assert "backend_health_status" in wrapper
    assert "stable_release_artifact_path" in wrapper
    assert "internal_validation_artifact_path" in wrapper
    assert "Set-ImmoAppHubRuntimeProfileEnv" in wrapper
    profile_artifact_index = wrapper.index("$phasePreflight.artifact_paths.hub_runtime_profile")
    profile_env_export_index = wrapper.index(
        "Set-ImmoAppHubRuntimeProfileEnv", profile_artifact_index
    )
    assert profile_artifact_index < profile_env_export_index
    assert profile_env_export_index < wrapper.index(
        "IMMOAPP_PROD_CONFIG_STRICT", profile_env_export_index
    )
    assert "overall_beta_status" in wrapper
    assert "local_internal_beta_status" in wrapper
    assert "public_beta_distribution_status" in wrapper
    assert "installed_app_inventory_status" in wrapper
    assert "install_lifecycle_status" in wrapper
    assert "setup_wizard_front_door_e2e_status" in wrapper
    assert "installed_app_front_door_connectivity_status" in wrapper
    assert "desktop_installer_release_proof_status" in wrapper
    assert "hub_install_status" in wrapper
    assert "hub_status_status" in wrapper
    assert "Publish-StableReleaseArtifacts" in wrapper
    assert "Copy-StableReleaseArtifact" in wrapper
    assert "stable_artifacts_manifest.json" in wrapper
    assert wrapper.index(
        "$Summary.stable_release_artifacts_manifest = $manifestPath"
    ) < wrapper.index("$copied.wrapper_summary_json")
    assert "Assert-PathOutsideRepo" in wrapper
    assert "Stable release artifact folder already exists" in wrapper
    assert "AllowReplaceReleaseArtifacts" in wrapper
    assert "exit $exitCode" in wrapper
    assert "NO-GO" in wrapper
    assert "rev-parse HEAD" in wrapper
    assert "status --short" in wrapper
    assert "Get-GeneratedResidue" in wrapper
    assert "Clear-PreviousValidationArtifacts" in wrapper
    assert "Deleting previous validation artifact" in wrapper
    assert ".tmp\\beta_release_validation" in wrapper
    assert ".tmp\\desktop_e2e_artifacts" in wrapper
    assert "desktop_installer_build_*" in wrapper
    assert '"ProgramData runtime data"' not in wrapper
    assert '"Docker volumes"' not in wrapper
    assert '"MinIO data"' not in wrapper
    assert "verify_release_backup_integrity.py" in wrapper
    assert "backup_release_bundle.ps1" in wrapper
    assert "restore_release_bundle.ps1" in wrapper
    assert wrapper.index("verify_release_backup_integrity.py") < wrapper.index(
        "backup_release_bundle.ps1"
    )
    assert "repair_local_dev_release_integrity.ps1" not in wrapper
    assert "run_e2e_release_validation.ps1" in wrapper
    assert "[int]$WarnFreeMemoryGb = 6" in wrapper
    assert "[int]$MinCriticalFreeMemoryGb = 1" in wrapper
    assert "[int]$MinCommitHeadroomGb = 2" in wrapper
    assert '"-WarnFreeMemoryGb"' in wrapper
    assert '"-MinCriticalFreeMemoryGb"' in wrapper
    assert '"-MinCommitHeadroomGb"' in wrapper
    assert "function Reset-BackendStackResources" in e2e_release
    assert 'Reset-BackendStackResources -Reason "before runner preflight"' in e2e_release
    assert 'Reset-BackendStackResources -Reason "before nightly suite"' not in e2e_release
    assert 'Invoke-DesktopE2E -Suite "smoke"' not in e2e_release
    assert 'Invoke-DesktopE2E -Suite "nightly" -RebuildBackend' in e2e_release
    assert e2e_release.index(
        'Reset-BackendStackResources -Reason "before runner preflight"'
    ) < e2e_release.index("Release E2E validation: resetting runner environment")
    assert '"checks.ps1", "-Stage", "pr"' in wrapper
    assert '"checks.ps1", "-Stage", "full"' in wrapper
    assert "GIT_EXE" in wrapper
    assert "INNO_SETUP_ISCC" in wrapper
    assert '[Environment]::GetEnvironmentVariable($EnvironmentVariable, "User")' in wrapper
    assert '[Environment]::GetEnvironmentVariable($EnvironmentVariable, "Machine")' in wrapper
    assert 'Join-Path $env:LOCALAPPDATA "Programs\\Inno Setup 6\\ISCC.exe"' in wrapper
    assert "AppData\\Local\\Programs\\Inno Setup 6\\ISCC.exe" in wrapper
    assert "iscc_version_text" in wrapper
    assert "iscc_product_version" in wrapper
    assert "iscc_file_version" in wrapper
    assert "iscc_version_source" in wrapper
    assert 'Join-Path $validationRoot "installer"' in wrapper
    assert '"-OutputRoot", $installerOutputRoot' in wrapper
    assert "6\\.7\\.1" not in wrapper
    assert "Get-BetaRequiredDockerServices" in wrapper
    assert "Get-ImmoAppHubRequiredComposeServices" in wrapper
    for service in (
        "db",
        "web",
        "worker",
        "worker-import",
        "worker-match",
        "worker-rebuild",
        "beat",
        "rabbitmq",
        "valkey",
        "minio",
        "openbao",
        "clamav",
    ):
        assert f'"{service}"' in common
    assert 'ps", "--format", "json"' in wrapper
    assert "Hub app stack is not healthy" in wrapper
    assert "docker_stack_start_attempted" in wrapper
    assert '"start Hub app stack"' in wrapper
    assert '"scripts\\stack.ps1", "-Action", "up"' in wrapper
    assert "Hub app stack is not healthy after start attempt" in wrapper
    assert "unhealthy_or_missing" in wrapper
    assert "http://127.0.0.1:8000/api/v1/health/" in wrapper
    assert "TimeoutSec 30" in wrapper
    assert "Backend health endpoint did not return 200" in wrapper
    assert "Start-Sleep" not in wrapper
    assert "function Wait-ComposeServiceHealthy" in stack
    assert "function Wait-ImmoAppServicesHealthy" in stack
    assert "TimeoutSeconds = 180" in stack
    assert "Waiting for compose service '$Service' readiness" in stack
    assert '"web", "worker", "worker-import", "worker-match", "worker-rebuild", "beat"' in stack
    assert 'Wait-ComposeServiceHealthy -ComposeArgs $base -Service "db"' in stack
    assert "Wait-ImmoAppServicesHealthy -ComposeArgs $app" in stack
    assert stack.count('Wait-ComposeServiceHealthy -ComposeArgs $base -Service "db"') >= 3
    assert 'Wait-ComposeServiceHealthy -ComposeArgs $full -Service "db"' in stack
    assert 'Wait-ComposeServiceHealthy -ComposeArgs $prod -Service "db"' in stack
    up_block = stack.split('    "up" {', 1)[1].split('    "up-existing" {', 1)[0]
    assert up_block.index(
        'Wait-ComposeServiceHealthy -ComposeArgs $base -Service "db"'
    ) < up_block.index('"immoapp_db_prepare"')
    assert "Inno Setup compiler not found through PATH or INNO_SETUP_ISCC" in wrapper
    assert "Fresh-machine install" in wrapper
    assert "LAN Hub/workstation" in wrapper
    assert "Assert-FreshMachineEvidence" in wrapper
    assert "immoapp_fresh_machine_install_evidence" in wrapper
    assert "Assert-InstalledAppInventoryEvidence" in wrapper
    assert "immoapp_installed_app_inventory" in wrapper
    assert "debug missing build identity allowance and cannot be GO" in wrapper
    assert "must verify installer SHA from the installer file" in wrapper
    assert "Assert-InstallLifecycleEvidence" in wrapper
    assert "immoapp_install_lifecycle_evidence" in wrapper
    assert "older lifecycle schemas prove mechanics only" in wrapper
    assert "post_uninstall phase must prove registry and installed exe absent" in wrapper
    assert "Assert-ManualProductProofEvidence" in wrapper
    assert "immoapp_manual_product_proof_evidence" in wrapper
    assert "Assert-LanEvidence" in wrapper
    assert "immoapp_lan_hub_workstation_evidence" in wrapper
    assert "Assert-HubInstallEvidence" in wrapper
    assert "Assert-HubStatusEvidence" in wrapper
    assert "immoapp_hub_install_evidence" in wrapper
    assert "immoapp_hub_status_evidence" in wrapper
    assert "detect_hub_runtime.ps1" in wrapper
    assert "hub_runtime_detection_json" in wrapper
    assert "runtime_detection from detect_hub_runtime.ps1" in wrapper
    assert "runtime_dependency_mode=manual_docker_desktop" in wrapper
    assert "agency_install_status=GO" in wrapper
    assert "backend_url_is_localhost" in wrapper
    assert "cannot use localhost desktop_backend_url for workstation proof" in wrapper
    assert "cannot use localhost hub_base_url for workstation proof" in wrapper
    assert "installer_sha256 does not match wrapper installer hash" in wrapper
    assert "source_commit_sha does not match wrapper commit SHA" in wrapper
    assert (
        'foreach ($field in @("evidence_file_sha256", "copied_from_machine", "copied_at_utc"))'
        in wrapper
    )
    assert "Assert-LocalEvidencePath" in wrapper
    assert "Assert-RemoteEvidenceHash" in wrapper
    assert "Assert-LocalOrRemoteSupportBundleProof" in wrapper
    assert "Assert-EmbeddedOrLocalReachabilityProof" in wrapper
    assert "immoapp_lan_workstation_reachability_proof" in wrapper
    assert "uninstall_reinstall_behavior=confirmed" in wrapper
    assert (
        "NOT A COMPLETE BETA RELEASE. Installer artifact is available only for proof execution."
        in wrapper
    )
    assert "bundle_inventory_path" in wrapper
    assert "bundle_inventory_sha256" in wrapper
    assert "package_inventory_path must match bundle_inventory_path" in wrapper
    assert "package_inventory_sha256 must match bundle_inventory_sha256" in wrapper
    assert "Assert-BundleInventoryEvidence" in wrapper
    assert "immoapp_installer_package_inventory" in wrapper
    assert "desktop_and_or_hub" in wrapper
    assert "supports_desktop_only" in wrapper
    assert "supports_hub_only" in wrapper
    assert "supports_desktop_and_hub" in wrapper
    assert "WslPolicyEvidenceJson" in wrapper
    assert "ValidationScope" in wrapper
    assert '"desktop_only", "hub_only", "desktop_and_hub"' in wrapper
    assert "Assert-WslPolicyEvidence" in wrapper
    assert "WSL2 policy planning cannot satisfy agency install" in wrapper
    assert '$ValidationScope -eq "desktop_only"' in wrapper
    assert 'Complete-Phase -Phase $phaseWslPolicy -Status "N/A"' in wrapper
    assert "WSL2 policy evidence was not provided." in wrapper
    assert "managed_wsl2_container_runtime_candidate" in wrapper
    assert "managed_wsl2_container_runtime_artifact" in wrapper
    assert "runtime_artifact_status" in wrapper
    assert "runtime_start_status" in wrapper
    assert "runtime_artifact_status and runtime_start_status are both GO" in wrapper
    assert "candidate/artifact proof for managed runtime GO" in wrapper
    assert "detected forbidden packaged paths" in wrapper
    assert "installer_signed" in wrapper
    assert "public_beta_distribution" in wrapper
    assert "evidence file was not provided" in wrapper
    detector = _read("scripts/detect_hub_runtime.ps1")
    register = _read("scripts/register_managed_hub_runtime_provider.ps1")
    assert "managed_wsl2_container_runtime_candidate" in detector
    assert "managed_wsl2_container_runtime_artifact" in detector
    assert "managed_wsl2_runtime_artifact_missing" in detector
    assert "managed_wsl2_runtime_start_not_proven" in detector
    assert "managed_wsl2_front_door_live_probe_failed" in detector
    assert "runtime_start_evidence_sha256" in detector
    assert "managed_runtime_command_path" in detector
    assert "front_door_health_status" in detector
    assert 'agencyStatus = "NO_GO"' in detector
    assert "RuntimeDependencyMode" in register
    assert "RuntimeArtifactInventoryJson" in register
    assert "WslPolicyJsonPath" in register
    start_evidence = _read("scripts/collect_managed_wsl2_runtime_start_evidence.ps1")
    assert "immoapp_managed_wsl2_runtime_start_evidence" in start_evidence
    assert "start_run_id" in start_evidence
    assert "provider_config_sha256" in start_evidence
    assert "runtime_artifact_inventory_sha256" in start_evidence
    assert "X-ImmoApp-Front-Door" in start_evidence
    assert "immoapp_hub_front_door_identity" in start_evidence


def _run_wsl_policy_phase(
    policy: Path | None,
    *,
    validation_scope: str = "hub_only",
    config_root: Path | None = None,
) -> dict[str, Any]:
    wrapper = REPO_ROOT / "scripts" / "run_beta_release_validation.ps1"
    policy_arg = f" -WslPolicyEvidenceJson '{policy}'" if policy is not None else ""
    config_root_command = ""
    if config_root is not None:
        config_root_command = f"function Get-ImmoAppRuntimePaths {{ [pscustomobject]@{{ ConfigRoot = '{config_root}' }} }}\n"
    command = f"""
    $source = Get-Content -LiteralPath '{wrapper}' -Raw
    $prefix = $source.Substring(0, $source.IndexOf('$repoRoot ='))
    $prefix = $prefix -replace '\\. \\(Join-Path \\$PSScriptRoot "common\\.ps1"\\)', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppSecurityEnv\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Import-ImmoAppEnvFile\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppHostRuntimeEndpoints\\r?\\n', ''
    . ([scriptblock]::Create($prefix))
    {config_root_command}
    Resolve-WslPolicyPhaseEvidence -ValidationScope '{validation_scope}'{policy_arg} | ConvertTo-Json -Depth 8
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return cast(dict[str, Any], json.loads(result.stdout))


def _write_wsl_policy(
    path: Path,
    *,
    runtime_profile_source: str,
    runtime_profile_status: str,
    runtime_profile_path: str,
    runtime_profile_sha256: str,
    observed_hub_runtime_profile: str,
    planned_wsl_memory_gb: int = 8,
    planned_wsl_processors: int = 6,
    selected_hub_runtime_profile: str | None = "medium",
) -> None:
    payload: dict[str, Any] = {
        "kind": "immoapp_managed_wsl2_runtime_policy",
        "schema_version": 1,
        "policy_result": "GO",
        "agency_install_status": "NO_GO",
        "cap_is_ceiling_not_reservation": True,
        "global_wsl_config_scope": True,
        "total_memory_gb": 16,
        "hub_minimum_ram_gb": 8,
        "planned_wsl_memory_gb": planned_wsl_memory_gb,
        "planned_wsl_processors": planned_wsl_processors,
        "runtime_profile_source": runtime_profile_source,
        "runtime_profile_status": runtime_profile_status,
        "runtime_profile_path": runtime_profile_path,
        "runtime_profile_sha256": runtime_profile_sha256,
        "runtime_profile_error": "",
        "observed_hub_runtime_profile": observed_hub_runtime_profile,
    }
    if selected_hub_runtime_profile is not None:
        payload["selected_hub_runtime_profile"] = selected_hub_runtime_profile
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_wsl_policy_release_scope_helper_is_behavioral_and_scope_aware(
    tmp_path: Path,
) -> None:
    wrapper = REPO_ROOT / "scripts" / "run_beta_release_validation.ps1"
    policy = tmp_path / "wsl-policy.json"
    policy.write_text(
        json.dumps(
            {
                "kind": "immoapp_managed_wsl2_runtime_policy",
                "schema_version": 1,
                "policy_result": "GO",
                "agency_install_status": "NO_GO",
                "cap_is_ceiling_not_reservation": True,
                "global_wsl_config_scope": True,
                "total_memory_gb": 16,
                "hub_minimum_ram_gb": 8,
                "planned_wsl_memory_gb": 8,
                "planned_wsl_processors": 6,
                "selected_hub_runtime_profile": "medium",
                "runtime_profile_source": "machine_capacity",
                "runtime_profile_status": "missing",
                "runtime_profile_path": "",
                "runtime_profile_sha256": "",
                "runtime_profile_error": "",
                "observed_hub_runtime_profile": "",
            }
        ),
        encoding="utf-8",
    )
    command = f"""
    $source = Get-Content -LiteralPath '{wrapper}' -Raw
    $prefix = $source.Substring(0, $source.IndexOf('$repoRoot ='))
    $prefix = $prefix -replace '\\. \\(Join-Path \\$PSScriptRoot "common\\.ps1"\\)', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppSecurityEnv\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Import-ImmoAppEnvFile\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppHostRuntimeEndpoints\\r?\\n', ''
    . ([scriptblock]::Create($prefix))
    [ordered]@{{
      desktop_only = Resolve-WslPolicyPhaseEvidence -ValidationScope 'desktop_only'
      hub_only_missing = Resolve-WslPolicyPhaseEvidence -ValidationScope 'hub_only'
      combined_missing = Resolve-WslPolicyPhaseEvidence -ValidationScope 'desktop_and_hub'
      hub_only_valid = Resolve-WslPolicyPhaseEvidence -ValidationScope 'hub_only' -WslPolicyEvidenceJson '{policy}'
    }} | ConvertTo-Json -Depth 8
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["desktop_only"]["status"] == "N/A"
    assert payload["hub_only_missing"]["status"] == "NO-GO"
    assert payload["hub_only_missing"]["reason"] == "WSL2 policy evidence was not provided."
    assert payload["combined_missing"]["status"] == "NO-GO"
    assert payload["combined_missing"]["reason"] == "WSL2 policy evidence was not provided."
    assert payload["hub_only_valid"]["status"] == "GO"
    assert payload["hub_only_valid"]["agency_install_status"] == "NO_GO"
    assert payload["hub_only_valid"]["planned_wsl_memory_gb"] == 8


def test_wsl_policy_release_scope_rejects_missing_runtime_profile_provenance(
    tmp_path: Path,
) -> None:
    wrapper = REPO_ROOT / "scripts" / "run_beta_release_validation.ps1"
    policy = tmp_path / "wsl-policy-missing-provenance.json"
    policy.write_text(
        json.dumps(
            {
                "kind": "immoapp_managed_wsl2_runtime_policy",
                "schema_version": 1,
                "policy_result": "GO",
                "agency_install_status": "NO_GO",
                "cap_is_ceiling_not_reservation": True,
                "global_wsl_config_scope": True,
                "total_memory_gb": 16,
                "hub_minimum_ram_gb": 8,
                "planned_wsl_memory_gb": 8,
                "planned_wsl_processors": 6,
                "runtime_profile_source": "machine_capacity",
                "runtime_profile_status": "missing",
                "runtime_profile_path": "",
                "runtime_profile_error": "",
                "observed_hub_runtime_profile": "",
            }
        ),
        encoding="utf-8",
    )
    command = f"""
    $source = Get-Content -LiteralPath '{wrapper}' -Raw
    $prefix = $source.Substring(0, $source.IndexOf('$repoRoot ='))
    $prefix = $prefix -replace '\\. \\(Join-Path \\$PSScriptRoot "common\\.ps1"\\)', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppSecurityEnv\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Import-ImmoAppEnvFile\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppHostRuntimeEndpoints\\r?\\n', ''
    . ([scriptblock]::Create($prefix))
    Resolve-WslPolicyPhaseEvidence -ValidationScope 'hub_only' -WslPolicyEvidenceJson '{policy}' | ConvertTo-Json -Depth 8
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "NO-GO"
    assert (
        payload["reason"]
        == "WSL2 policy evidence missing runtime profile provenance field: runtime_profile_sha256"
    )


def test_wsl_policy_release_scope_rejects_missing_runtime_profile_path(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "wsl-policy-missing-profile-path.json"
    missing_profile = tmp_path / "hub_runtime_profile.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(missing_profile),
        runtime_profile_sha256="0" * 64,
        observed_hub_runtime_profile="medium",
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "missing local runtime_profile_path" in payload["reason"]


def test_wsl_policy_release_scope_rejects_default_profile_arbitrary_path(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "ProgramData" / "ImmoApp" / "config"
    config_root.mkdir(parents=True)
    arbitrary_profile = tmp_path / "elsewhere" / "hub_runtime_profile.json"
    arbitrary_profile.parent.mkdir()
    arbitrary_profile.write_text(
        json.dumps({"selected_profile": "medium"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-default-arbitrary-profile.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="default_persisted_config",
        runtime_profile_status="valid",
        runtime_profile_path=str(arbitrary_profile),
        runtime_profile_sha256=hashlib.sha256(arbitrary_profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="medium",
    )

    payload = _run_wsl_policy_phase(policy, config_root=config_root)

    assert payload["status"] == "NO-GO"
    assert "active config root hub_runtime_profile.json" in payload["reason"]


def test_wsl_policy_release_scope_accepts_default_profile_active_config_path(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "ProgramData" / "ImmoApp" / "config"
    config_root.mkdir(parents=True)
    profile = config_root / "hub_runtime_profile.json"
    profile.write_text(
        json.dumps({"selected_profile": "medium"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-default-active-profile.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="default_persisted_config",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="medium",
    )

    payload = _run_wsl_policy_phase(policy, config_root=config_root)

    assert payload["status"] == "GO"
    assert payload["agency_install_status"] == "NO_GO"


def test_wsl_policy_release_scope_rejects_runtime_profile_sha_mismatch(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "hub_runtime_profile.json"
    profile.write_text(
        json.dumps({"selected_profile": "medium"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-stale-profile.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256="0" * 64,
        observed_hub_runtime_profile="medium",
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "SHA mismatch" in payload["reason"]


def test_wsl_policy_release_scope_rejects_uppercase_runtime_profile_sha(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "explicit_runtime_profile.json"
    profile.write_text(
        json.dumps({"selected_profile": "tiny"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-uppercase-sha.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest().upper(),
        observed_hub_runtime_profile="tiny",
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "valid runtime_profile_sha256" in payload["reason"]


def test_wsl_policy_release_scope_rejects_observed_profile_mismatch(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "explicit_runtime_profile.json"
    profile.write_text(
        json.dumps({"selected_profile": "tiny"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-profile-mismatch.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="medium",
        planned_wsl_memory_gb=3,
        planned_wsl_processors=2,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "observed_hub_runtime_profile mismatch" in payload["reason"]


def test_wsl_policy_release_scope_rejects_memory_above_profile_cap(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "explicit_runtime_profile.json"
    profile.write_text(
        json.dumps({"selected_profile": "tiny"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-memory-above-cap.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="tiny",
        planned_wsl_memory_gb=4,
        planned_wsl_processors=2,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "planned_wsl_memory_gb exceeds observed runtime profile cap" in payload["reason"]


def test_wsl_policy_release_scope_rejects_processors_above_profile_cap(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "explicit_runtime_profile.json"
    profile.write_text(
        json.dumps({"selected_profile": "tiny"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-processors-above-cap.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="tiny",
        planned_wsl_memory_gb=3,
        planned_wsl_processors=3,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "planned_wsl_processors exceeds observed runtime profile cap" in payload["reason"]


def test_wsl_policy_release_scope_rejects_invalid_runtime_profile_json(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "explicit_runtime_profile.json"
    profile.write_text("{not json", encoding="utf-8")
    policy = tmp_path / "wsl-policy-invalid-profile-json.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="medium",
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "runtime profile JSON is invalid" in payload["reason"]


def test_wsl_policy_release_scope_rejects_runtime_profile_missing_selector(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "explicit_runtime_profile.json"
    profile.write_text(json.dumps({"note": "missing selector"}), encoding="utf-8")
    policy = tmp_path / "wsl-policy-missing-selector.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="medium",
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "missing selected_profile/profile_name" in payload["reason"]


def test_wsl_policy_release_scope_rejects_unsupported_runtime_profile(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "explicit_runtime_profile.json"
    profile.write_text(json.dumps({"profile_name": "huge"}), encoding="utf-8")
    policy = tmp_path / "wsl-policy-unsupported-profile.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="medium",
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "unsupported selected profile" in payload["reason"]


def test_wsl_policy_release_scope_accepts_explicit_matching_runtime_profile_sha(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "explicit_runtime_profile.json"
    profile.write_text(
        json.dumps({"selected_profile": "tiny"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-valid-profile.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="explicit_runtime_profile_json",
        runtime_profile_status="valid",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="tiny",
        planned_wsl_memory_gb=3,
        planned_wsl_processors=2,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "GO"
    assert payload["agency_install_status"] == "NO_GO"


def test_wsl_policy_release_scope_rejects_machine_capacity_with_profile_path(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "hub_runtime_profile.json"
    profile.write_text(
        json.dumps({"selected_profile": "medium"}),
        encoding="utf-8",
    )
    policy = tmp_path / "wsl-policy-bad-machine-capacity.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="machine_capacity",
        runtime_profile_status="missing",
        runtime_profile_path=str(profile),
        runtime_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
        observed_hub_runtime_profile="medium",
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert (
        "machine-capacity policy must not record runtime profile path/hash/profile"
        in payload["reason"]
    )


def test_wsl_policy_release_scope_rejects_machine_capacity_memory_above_cap(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "wsl-policy-machine-memory-above-cap.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="machine_capacity",
        runtime_profile_status="missing",
        runtime_profile_path="",
        runtime_profile_sha256="",
        observed_hub_runtime_profile="",
        selected_hub_runtime_profile="medium",
        planned_wsl_memory_gb=999,
        planned_wsl_processors=6,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert (
        "machine-capacity planned_wsl_memory_gb exceeds selected_hub_runtime_profile cap"
        in payload["reason"]
    )


def test_wsl_policy_release_scope_rejects_machine_capacity_processors_above_cap(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "wsl-policy-machine-processors-above-cap.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="machine_capacity",
        runtime_profile_status="missing",
        runtime_profile_path="",
        runtime_profile_sha256="",
        observed_hub_runtime_profile="",
        selected_hub_runtime_profile="medium",
        planned_wsl_memory_gb=8,
        planned_wsl_processors=999,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert (
        "machine-capacity planned_wsl_processors exceeds selected_hub_runtime_profile cap"
        in payload["reason"]
    )


def test_wsl_policy_release_scope_rejects_machine_capacity_missing_selected_profile(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "wsl-policy-machine-missing-selected-profile.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="machine_capacity",
        runtime_profile_status="missing",
        runtime_profile_path="",
        runtime_profile_sha256="",
        observed_hub_runtime_profile="",
        selected_hub_runtime_profile=None,
        planned_wsl_memory_gb=8,
        planned_wsl_processors=6,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "missing required field: selected_hub_runtime_profile" in payload["reason"]


def test_wsl_policy_release_scope_rejects_machine_capacity_invalid_selected_profile(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "wsl-policy-machine-invalid-selected-profile.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="machine_capacity",
        runtime_profile_status="missing",
        runtime_profile_path="",
        runtime_profile_sha256="",
        observed_hub_runtime_profile="",
        selected_hub_runtime_profile="huge",
        planned_wsl_memory_gb=8,
        planned_wsl_processors=6,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "NO-GO"
    assert "invalid selected_hub_runtime_profile" in payload["reason"]


def test_wsl_policy_release_scope_accepts_valid_machine_capacity_caps(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "wsl-policy-machine-valid-caps.json"
    _write_wsl_policy(
        policy,
        runtime_profile_source="machine_capacity",
        runtime_profile_status="missing",
        runtime_profile_path="",
        runtime_profile_sha256="",
        observed_hub_runtime_profile="",
        selected_hub_runtime_profile="medium",
        planned_wsl_memory_gb=8,
        planned_wsl_processors=6,
    )

    payload = _run_wsl_policy_phase(policy)

    assert payload["status"] == "GO"
    assert payload["agency_install_status"] == "NO_GO"


def test_stable_manifest_cannot_claim_complete_beta_without_fresh_and_lan() -> None:
    wrapper = _read("scripts/run_beta_release_validation.ps1")

    assert "overall_beta_status" in wrapper
    assert "local_internal_beta_status" in wrapper
    assert "public_beta_distribution_status" in wrapper
    assert "fresh_machine_status" in wrapper
    assert "lan_hub_workstation_status" in wrapper
    assert "hub_install_status" in wrapper
    assert "hub_status_status" in wrapper
    assert "installed_app_inventory_status" in wrapper
    assert "install_lifecycle_status" in wrapper
    assert "desktop_installer_release_proof_status" in wrapper
    assert "complete_beta_release_candidate" in wrapper
    assert (
        "NOT A COMPLETE BETA RELEASE. Installer artifact is available only for proof execution."
        in wrapper
    )
    assert "$completeRequiredGo.Count -eq 0" in wrapper
    assert "$Summary.overall_beta_status = if ($completeRequiredGo.Count -eq 0" in wrapper
    assert "bundle_inventory_file_count" in wrapper
    assert "bundle_inventory_total_byte_size" in wrapper


def test_release_evidence_hardening_contracts_are_fail_closed() -> None:
    wrapper = _read("scripts/run_beta_release_validation.ps1")
    lifecycle = _read("scripts/collect_install_lifecycle_evidence.ps1")
    inventory = _read("scripts/collect_installed_app_inventory.ps1")
    fresh = _read("scripts/collect_fresh_machine_install_evidence.ps1")
    lan = _read("scripts/collect_lan_workstation_evidence.ps1")

    assert "schema_version must be 3; older lifecycle schemas prove mechanics only" in wrapper
    assert "install_mechanics_status must be GO" in wrapper
    assert "Installed desktop front-door connectivity" in wrapper
    assert "post_install phase must prove registry and installed exe present" in wrapper
    assert "post_uninstall phase must prove registry and installed exe absent" in wrapper
    assert "post_reinstall phase must prove registry and installed exe present again" in wrapper
    assert "evidence source_commit_sha does not match wrapper commit SHA" in wrapper
    assert "evidence installer_sha256 does not match wrapper installer hash" in wrapper
    assert "remote evidence must embed reachability_proof" in wrapper
    assert (
        'Assert-RemoteEvidenceHash -Data $data -Field "support_bundle_sha256" -Label $label'
        in wrapper
    )
    assert (
        "remote evidence must embed installed_inventory or record installed_inventory_sha256"
        in wrapper
    )
    assert (
        "remote evidence must embed install_lifecycle or record install_lifecycle_evidence_sha256"
        in wrapper
    )
    assert "requires installed_inventory_status=verified for GO" in wrapper
    assert "requires desktop_installer_release_proof_status=GO for GO" in wrapper
    assert "uninstall_reinstall_behavior=confirmed" in wrapper

    assert "post_uninstall requires uninstall registry absent" in lifecycle
    assert "post_uninstall requires installed ImmoApp.exe absent" in lifecycle
    assert "single final installed state" not in lifecycle.lower()
    assert "installer_sha256_claimed_by_operator" in inventory
    assert "installer_sha256_verified" in inventory
    assert "installer_sha256_claimed_only" in inventory
    assert "claimed_only_by_operator" in inventory
    assert "AllowMissingBuildIdentityForDebug" in inventory
    assert "Debug" in inventory
    assert "install path guessing is not allowed" in fresh
    assert "missing_explicit_exe_only" in fresh
    assert "schema_version = 2" in lan


def test_lan_reachability_helper_is_read_only_health_proof() -> None:
    helper = _read("scripts/verify_lan_workstation_reachability.ps1")

    assert "Set-StrictMode -Version Latest" in helper
    assert "[string]$HubBaseUrl" in helper
    assert "[string]$ExpectedBackendIdentity" in helper
    assert "[string]$OutputJson" in helper
    assert "[switch]$RequireWorkstationUrl" in helper
    assert "[int]$ExpectedHealthStatus = 200" in helper
    assert "HubBaseUrl cannot be localhost when -RequireWorkstationUrl" in helper
    assert '"/api/v1/health/"' in helper
    assert "Invoke-WebRequest -Method Get -Uri $healthUrl" in helper
    assert "health_status" in helper
    assert "tcp_connectivity_result" in helper
    assert "backend_url_is_localhost" in helper
    assert "is_workstation_candidate" in helper
    assert "dns_resolution" in helper
    assert "network_adapters" in helper
    assert "network_adapter_summary" in helper
    assert "machine_name" in helper
    assert "immoapp_lan_workstation_reachability_proof" in helper
    assert "mutation_routes_used = $false" in helper
    for forbidden in ("-Method Post", "-Method Put", "-Method Patch", "-Method Delete"):
        assert forbidden not in helper
    for mutation_route in (
        "faults/inject",
        "pause-next",
        "notifications/publish",
        "revoke-session",
    ):
        assert mutation_route not in helper


def test_current_machine_beta_evidence_helpers_exist_and_are_strict() -> None:
    installed = _read("scripts/collect_installed_app_inventory.ps1")
    lifecycle = _read("scripts/collect_install_lifecycle_evidence.ps1")
    fresh = _read("scripts/collect_fresh_machine_install_evidence.ps1")
    manual = _read("scripts/write_manual_product_proof_evidence.ps1")
    lan = _read("scripts/collect_lan_workstation_evidence.ps1")

    assert "immoapp_installed_app_inventory" in installed
    assert "uninstall_registry_entry" in installed
    assert "forbidden_path_matches" in installed
    assert "Installed app inventory found forbidden" in installed
    assert "installer_sha256_claimed_by_operator" in installed
    assert "verified_from_installer_file" in installed
    assert "claimed_only_by_operator" in installed
    assert "AllowMissingBuildIdentityForDebug" in installed
    assert "Installed app build identity is required" in installed
    assert "installer_build_identity" in installed
    assert "bundle inventory hash does not match build summary" in installed
    for forbidden in ("server", "scripts", "deployment", "docs", ".git", ".tmp", "__pycache__"):
        assert forbidden in installed

    assert "immoapp_install_lifecycle_evidence" in lifecycle
    assert "schema_version = 3" in lifecycle
    assert (
        'ValidateSet("post_install", "post_uninstall", "post_reinstall", "combined_manual")'
        in lifecycle
    )
    assert "post_uninstall requires uninstall registry absent" in lifecycle
    assert "post_uninstall requires installed ImmoApp.exe absent" in lifecycle
    assert "post_reinstall requires uninstall registry present" in lifecycle
    assert "phase_evidence_files" in lifecycle
    assert "installed_app_front_door_connectivity_status" in lifecycle
    assert "desktop_installer_release_proof_status" in lifecycle
    assert "lifecycle_status = $lifecycleStatus" in lifecycle
    assert "-Method Post" not in lifecycle
    assert "mutation_routes_used = $false" in lifecycle

    assert "immoapp_fresh_machine_install_evidence" in fresh
    assert "schema_version = 2" in fresh
    assert "[string]$InstalledExePath" in fresh
    assert "Installer SHA-256 mismatch" in fresh
    assert "/api/v1/health/" in fresh
    assert "Fresh-machine evidence requires an existing support bundle path" in fresh
    assert "install path guessing is not allowed" in fresh
    assert "installed_inventory_status = $installedInventoryStatus" in fresh
    assert "missing_explicit_exe_only" in fresh
    assert "Install lifecycle evidence must have desktop_installer_release_proof_status=GO" in fresh
    assert "-Method Post" not in fresh
    assert "mutation_routes_used = $false" in fresh

    assert "immoapp_manual_product_proof_evidence" in manual
    assert "OwnerLoginConfirmed" in manual
    assert "CrudConfirmed" in manual
    assert "OfferPhotoThumbnailConfirmed" in manual
    assert "support_bundle_sha256" in manual
    assert "mutation_routes_used = $false" in manual

    assert "immoapp_lan_hub_workstation_evidence" in lan
    assert "schema_version = 2" in lan
    assert "ReachabilityProofJson" in lan
    assert "LAN workstation evidence requires source commit SHA" in lan
    assert "LAN workstation evidence requires installer SHA-256" in lan
    assert "LAN workstation evidence rejects localhost desktop_backend_url" in lan
    assert "LAN workstation evidence requires a Hub IP/hostname URL, not localhost" in lan
    assert "workstation_support_bundle_sha256" in lan
    assert "HubBackupRestoreConfirmed" in lan
    assert "UninstallReinstallDeferredWithReason" in lan
    assert "-Method Post" not in lan
    assert "mutation_routes_used = $false" in lan


def test_beta_release_validation_evidence_contracts_reject_wrong_kind_and_localhost(
    tmp_path: Path,
) -> None:
    wrapper = REPO_ROOT / "scripts" / "run_beta_release_validation.ps1"
    wrong_fresh = tmp_path / "wrong_fresh.json"
    wrong_fresh.write_text(
        json.dumps({"kind": "wrong", "schema_version": 1}),
        encoding="utf-8",
    )
    reachability = tmp_path / "reachability.json"
    reachability.write_text(
        json.dumps(
            {
                "kind": "immoapp_lan_workstation_reachability_proof",
                "schema_version": 1,
                "hub_base_url": "http://hub.local:8000",
                "health_status": 200,
            }
        ),
        encoding="utf-8",
    )
    lan = tmp_path / "lan.json"
    lan.write_text(
        json.dumps(
            {
                "kind": "immoapp_lan_hub_workstation_evidence",
                "schema_version": 1,
                "created_at_utc": "2026-05-16T00:00:00Z",
                "hub_machine_name": "hub",
                "workstation_machine_or_profile_name": "workstation",
                "hub_base_url": "http://hub.local:8000",
                "desktop_backend_url": "http://127.0.0.1:8000",
                "backend_url_is_localhost": True,
                "reachability_proof_path": str(reachability),
                "health_status": 200,
                "network_type": "Ethernet",
                "windows_firewall_rule_status": "verified",
                "owner_login_proof": "ok",
                "workstation_create_read_update_proof": "ok",
                "workstation_offer_photo_thumbnail_proof": "ok",
                "workstation_support_bundle_path": str(tmp_path),
                "hub_backup_restore_proof": "ok",
                "uninstall_reinstall_behavior": "ok",
            }
        ),
        encoding="utf-8",
    )
    lan_dev_source = tmp_path / "lan_dev_source.json"
    lan_dev_source.write_text(
        json.dumps(
            {
                "kind": "immoapp_lan_hub_workstation_evidence",
                "schema_version": 2,
                "created_at_utc": "2026-05-16T00:00:00Z",
                "source_commit_sha": "abc",
                "installer_sha256": "0" * 64,
                "hub_machine_name": "hub",
                "workstation_machine_or_profile_name": "workstation",
                "hub_base_url": "http://hub.local:8000",
                "desktop_backend_url": "http://workstation.local:8000",
                "backend_url_is_localhost": False,
                "connection_source": "local_dev_unverified",
                "reachability_proof_path": str(reachability),
                "reachability_proof": {},
                "health_status": 200,
                "network_type": "Ethernet",
                "windows_firewall_rule_status": "verified",
                "owner_login_proof": True,
                "workstation_create_read_update_proof": True,
                "workstation_offer_photo_thumbnail_proof": True,
                "workstation_support_bundle_path": str(tmp_path),
                "workstation_support_bundle_sha256": "0" * 64,
                "hub_backup_restore_proof": True,
                "uninstall_reinstall_behavior": "confirmed",
            }
        ),
        encoding="utf-8",
    )
    command = f"""
    $source = Get-Content -LiteralPath '{wrapper}' -Raw
    $prefix = $source.Substring(0, $source.IndexOf('$repoRoot ='))
    $prefix = $prefix -replace '\\. \\(Join-Path \\$PSScriptRoot "common\\.ps1"\\)', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppSecurityEnv\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Import-ImmoAppEnvFile\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppHostRuntimeEndpoints\\r?\\n', ''
    . ([scriptblock]::Create($prefix))
    try {{
      Assert-FreshMachineEvidence -Path '{wrong_fresh}' -CommitSha '' -InstallerSha256 ''
      throw 'accepted wrong fresh evidence kind'
    }} catch {{
      if ($_.Exception.Message -eq 'accepted wrong fresh evidence kind') {{ throw }}
    }}
    try {{
      Assert-LanEvidence -Path '{lan}' -CommitSha '' -InstallerSha256 ''
      throw 'accepted LAN localhost backend URL'
    }} catch {{
      if ($_.Exception.Message -eq 'accepted LAN localhost backend URL') {{ throw }}
    }}
    try {{
      Assert-LanEvidence -Path '{lan_dev_source}' -CommitSha '' -InstallerSha256 ''
      throw 'accepted LAN local_dev_unverified endpoint source'
    }} catch {{
      if ($_.Exception.Message -eq 'accepted LAN local_dev_unverified endpoint source') {{ throw }}
    }}
    exit 0
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_beta_release_validation_rejects_validate_only_or_skipped_firewall_foundation(
    tmp_path: Path,
) -> None:
    wrapper = REPO_ROOT / "scripts" / "run_beta_release_validation.ps1"

    def write_foundation(name: str, **overrides: object) -> Path:
        payload: dict[str, object] = {
            "kind": "immoapp_hub_installer_foundation_evidence",
            "schema_version": 1,
            "setup_run_id": "test-run-123",
            "selected_install_desktop": True,
            "selected_install_hub": True,
            "install_mode": "desktop_and_hub",
            "validate_only": False,
            "foundation_applied_status": "GO",
            "hub_foundation_status": "GO",
            "proof_result": "GO",
            "hub_identity_status": "GO",
            "hub_state_manifest_status": "GO",
            "hub_state_manifest_path": "C:/ProgramData/ImmoApp/config/hub_state_manifest.json",
            "directories_status": "GO",
            "front_door_status": "GO",
            "hub_display_name": "Main Office",
            "hub_front_door_url": "http://192.168.1.10:8000",
            "front_door_port": 8000,
            "lan_access_enabled": True,
            "firewall_status": "already_present_valid",
            "firewall": {
                "verified": True,
                "direction": "Inbound",
                "action": "Allow",
                "protocol": "TCP",
                "local_port": "8000",
                "profile": "Private",
            },
            "agency_install_status": "NO_GO",
            "public_beta_status": "NO_GO",
        }
        payload.update(overrides)
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    validate_only = write_foundation(
        "validate-only.json",
        validate_only=True,
        foundation_applied_status="NOT_APPLICABLE",
        hub_foundation_status="NOT_APPLICABLE",
        proof_result="NO-GO",
        firewall_status="intended",
        firewall={"verified": False},
    )
    skipped_firewall = write_foundation(
        "skipped-firewall.json",
        firewall_status="skipped_no_lan_requested",
        firewall={"verified": False},
    )
    missing_setup_run = write_foundation("missing-setup-run.json", setup_run_id="")
    missing_manifest = write_foundation("missing-manifest.json", hub_state_manifest_status="NO-GO")
    valid = write_foundation("valid.json")
    command = f"""
    $source = Get-Content -LiteralPath '{wrapper}' -Raw
    $prefix = $source.Substring(0, $source.IndexOf('$repoRoot ='))
    $prefix = $prefix -replace '\\. \\(Join-Path \\$PSScriptRoot "common\\.ps1"\\)', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppSecurityEnv\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Import-ImmoAppEnvFile\\r?\\n', ''
    $prefix = $prefix -replace '(?m)^Set-ImmoAppHostRuntimeEndpoints\\r?\\n', ''
    . ([scriptblock]::Create($prefix))
    try {{
      Assert-InstallerRoleEvidence -Path '{validate_only}'
      throw 'accepted validate-only foundation evidence'
    }} catch {{
      if ($_.Exception.Message -eq 'accepted validate-only foundation evidence') {{ throw }}
    }}
    try {{
      Assert-InstallerRoleEvidence -Path '{skipped_firewall}'
      throw 'accepted skipped firewall foundation evidence'
    }} catch {{
      if ($_.Exception.Message -eq 'accepted skipped firewall foundation evidence') {{ throw }}
    }}
    try {{
      Assert-InstallerRoleEvidence -Path '{missing_setup_run}'
      throw 'accepted missing setup run foundation evidence'
    }} catch {{
      if ($_.Exception.Message -eq 'accepted missing setup run foundation evidence') {{ throw }}
    }}
    try {{
      Assert-InstallerRoleEvidence -Path '{missing_manifest}'
      throw 'accepted missing Hub state manifest foundation evidence'
    }} catch {{
      if ($_.Exception.Message -eq 'accepted missing Hub state manifest foundation evidence') {{ throw }}
    }}
    $accepted = Assert-InstallerRoleEvidence -Path '{valid}'
    if ([string]$accepted.agency_install_status -ne 'NO_GO') {{ throw 'foundation mechanics changed agency status' }}
    exit 0
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def _write_hub_m1_evidence_fixture(
    tmp_path: Path,
    *,
    inventory_payload: dict[str, object] | None = None,
    backup_payload: dict[str, object] | None = None,
    source_sha: str = "a" * 40,
    installer_sha: str = "0" * 64,
) -> tuple[dict[str, Path], dict[str, str]]:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    canonical_provider = programdata / "config" / "hub_runtime_provider.json"
    canonical_provider.parent.mkdir(parents=True)

    def write_json(name: str, payload: dict[str, object]) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    runtime_detection = {
        "runtime_dependency_mode": "managed_container_runtime",
        "agency_install_status": "GO",
        "provider_validation_status": "valid",
        "reason_code": "managed_runtime_ready",
        "provider_config_path": str(canonical_provider),
    }
    hub_install = write_json(
        "hub_install.json",
        {
            "kind": "immoapp_hub_install_evidence",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "hub-test",
            "proof_result": "GO",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "runtime_dependency_mode": "managed_container_runtime",
            "agency_install_status": "GO",
            "runtime_detection": runtime_detection,
            "runtime_provider_proof": {"proof_only": False},
            "hub_manager_script_source": "installed",
            "desktop_exe_source": "installed",
            "hub_base_url": "http://192.168.1.10:8000",
            "installed_version": "test",
            "installed_build_identity": {},
        },
    )
    hub_status = write_json(
        "hub_status.json",
        {
            "kind": "immoapp_hub_status_evidence",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "hub-test",
            "proof_result": "GO",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "hub_status": "Online",
            "hub_base_url": "http://192.168.1.10:8000",
            "database_health": "ok",
            "storage_photos_health": "ok",
            "worker_health": "ok",
            "runtime_dependency_mode": "managed_container_runtime",
            "agency_install_status": "GO",
            "runtime_detection": runtime_detection,
            "runtime_provider_proof": {"proof_only": False},
        },
    )
    reachability = write_json(
        "reachability.json",
        {
            "kind": "immoapp_lan_workstation_reachability_proof",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "workstation-test",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "proof_result": "GO",
            "health_status": 200,
            "hub_base_url": "http://192.168.1.10:8000",
        },
    )
    product = write_json(
        "product.json",
        {
            "kind": "immoapp_manual_product_proof_evidence",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "workstation-test",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "proof_result": "GO",
            "owner_login_proof": True,
            "create_read_update_proof": True,
            "offer_photo_thumbnail_proof": True,
        },
    )
    backup_bundle = tmp_path / "backup.bundle"
    backup_bundle.write_bytes(b"backup")
    import hashlib

    backup_sha = hashlib.sha256(backup_bundle.read_bytes()).hexdigest()
    backup_base: dict[str, object] = {
        "kind": "immoapp_beta_release_backup_restore_evidence",
        "schema_version": 1,
        "created_at_utc": "2026-01-01T00:00:00Z",
        "machine_name": "hub-test",
        "proof_result": "GO",
        "restore_database": "immoapp_restore",
        "isolated_restore_bucket": "immoapp-restore-drill-20260101000000-aaaaaaaa",
        "storage_objects_checked": 1,
        "storage_objects_hash_verified": 1,
        "live_source_bucket_used_as_restore_target": False,
        "backup_bundle_path": str(backup_bundle),
        "backup_bundle_sha256": backup_sha,
        "source_commit_sha": source_sha,
        "installer_sha256": installer_sha,
    }
    if backup_payload:
        backup_base.update(backup_payload)
    backup = write_json("backup.json", backup_base)
    support_bundle = tmp_path / "support.zip"
    support_bundle.write_bytes(b"support")
    support_sha = hashlib.sha256(support_bundle.read_bytes()).hexdigest()
    support = write_json(
        "support.json",
        {
            "kind": "immoapp_support_bundle_manifest",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "hub-test",
            "proof_result": "GO",
            "bundle_path": str(support_bundle),
            "bundle_sha256": support_sha,
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
        },
    )
    inventory_base: dict[str, object] = {
        "kind": "immoapp_installed_inventory",
        "schema_version": 1,
        "created_at_utc": "2026-01-01T00:00:00Z",
        "machine_name": "hub-test",
        "proof_result": "GO",
        "source_commit_sha": source_sha,
        "installer_sha256": installer_sha,
        "installer_sha256_verified": True,
        "installer_sha256_claimed_only": False,
        "support_bundle_sha256": support_sha,
        "installed_exe_path": "C:/Program Files/ImmoApp/ImmoApp.exe",
        "installed_exe_sha256": "1" * 64,
        "forbidden_path_count": 0,
    }
    if inventory_payload:
        inventory_base.update(inventory_payload)
    inventory = write_json("inventory.json", inventory_base)
    lifecycle = write_json(
        "lifecycle.json",
        {
            "kind": "immoapp_install_lifecycle_evidence",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "hub-test",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "proof_result": "GO",
        },
    )

    return (
        {
            "hub_install": hub_install,
            "hub_status": hub_status,
            "reachability": reachability,
            "product": product,
            "backup": backup,
            "support": support,
            "inventory": inventory,
            "lifecycle": lifecycle,
        },
        {
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            "SOURCE_SHA": source_sha,
            "INSTALLER_SHA": installer_sha,
        },
    )


def _run_hub_m1_verifier(
    tmp_path: Path,
    paths: dict[str, Path],
    env_values: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    verifier = REPO_ROOT / "scripts" / "verify_hub_beta_m1_evidence.ps1"
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(verifier),
            "-HubInstallEvidenceJson",
            str(paths["hub_install"]),
            "-HubStatusEvidenceJson",
            str(paths["hub_status"]),
            "-WorkstationReachabilityJson",
            str(paths["reachability"]),
            "-WorkstationProductProofJson",
            str(paths["product"]),
            "-BackupRestoreProofJson",
            str(paths["backup"]),
            "-SupportBundleManifestJson",
            str(paths["support"]),
            "-InstalledInventoryJson",
            str(paths["inventory"]),
            "-InstallLifecycleEvidenceJson",
            str(paths["lifecycle"]),
            "-SourceCommitSha",
            env_values["SOURCE_SHA"],
            "-InstallerSha256",
            env_values["INSTALLER_SHA"],
            "-OutputJson",
            str(tmp_path / "out.json"),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": env_values["IMMOAPP_TEST_PROGRAMDATA_ROOT"],
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )


def _make_junction(link: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_install_lifecycle_mechanics_only_is_not_full_desktop_release_proof(
    tmp_path: Path,
) -> None:
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"installer")
    installer_sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    source_sha = "a" * 40

    phase_paths: dict[str, Path] = {}
    for phase in ("post_install", "post_uninstall", "post_reinstall"):
        path = tmp_path / f"{phase}.json"
        path.write_text(
            json.dumps(
                {
                    "kind": "immoapp_install_lifecycle_evidence",
                    "schema_version": 3,
                    "source_commit_sha": source_sha,
                    "installer_sha256": installer_sha,
                    "phases": {phase: {"phase": phase}},
                }
            ),
            encoding="utf-8",
        )
        phase_paths[phase] = path

    output = tmp_path / "combined.json"
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "collect_install_lifecycle_evidence.ps1"),
            "-Mode",
            "combined_manual",
            "-InstallerPath",
            str(installer),
            "-InstallerSha256",
            installer_sha,
            "-SourceCommitSha",
            source_sha,
            "-OutputJson",
            str(output),
            "-PostInstallEvidenceJson",
            str(phase_paths["post_install"]),
            "-PostUninstallEvidenceJson",
            str(phase_paths["post_uninstall"]),
            "-PostReinstallEvidenceJson",
            str(phase_paths["post_reinstall"]),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(output.read_text(encoding="utf-8-sig"))
    assert evidence["schema_version"] == 3
    assert evidence["install_mechanics_status"] == "GO"
    assert evidence["installed_app_front_door_connectivity_status"] == "NOT_PROVEN"
    assert evidence["desktop_installer_release_proof_status"] == "NO-GO"
    assert evidence["lifecycle_status"] == "NO-GO"


def test_installed_desktop_front_door_evidence_rejects_direct_backend_port(
    tmp_path: Path,
) -> None:
    exe = tmp_path / "ImmoApp.exe"
    exe.write_bytes(b"exe")
    output = tmp_path / "front-door.json"
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "collect_installed_desktop_front_door_evidence.ps1"),
            "-InstalledExePath",
            str(exe),
            "-FrontDoorUrl",
            "http://127.0.0.1:18000",
            "-InstallerSha256",
            "1" * 64,
            "-SourceCommitSha",
            "a" * 40,
            "-OutputJson",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "refuses backend/internal service ports" in (result.stderr + result.stdout)


def test_hub_beta_m1_verifier_rejects_mixed_hub_status_commit(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    hub_status = json.loads(paths["hub_status"].read_text(encoding="utf-8"))
    hub_status["source_commit_sha"] = "b" * 40
    paths["hub_status"].write_text(json.dumps(hub_status), encoding="utf-8")

    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "Hub status evidence source_commit_sha does not match" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_evidence_path_through_junction(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    real_dir = tmp_path / "real-evidence"
    real_dir.mkdir()
    copied = real_dir / "hub_status.json"
    copied.write_text(paths["hub_status"].read_text(encoding="utf-8"), encoding="utf-8")
    junction = tmp_path / "junction-evidence"
    _make_junction(junction, real_dir)
    paths["hub_status"] = junction / "hub_status.json"

    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    assert "reparse point" in (result.stderr + result.stdout)


def test_hub_beta_m1_verifier_rejects_unsafe_output_json_parent(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    real_output = tmp_path / "real-output"
    junction_output = tmp_path / "junction-output"
    _make_junction(junction_output, real_output)
    verifier = REPO_ROOT / "scripts" / "verify_hub_beta_m1_evidence.ps1"
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(verifier),
            "-HubInstallEvidenceJson",
            str(paths["hub_install"]),
            "-HubStatusEvidenceJson",
            str(paths["hub_status"]),
            "-WorkstationReachabilityJson",
            str(paths["reachability"]),
            "-WorkstationProductProofJson",
            str(paths["product"]),
            "-BackupRestoreProofJson",
            str(paths["backup"]),
            "-SupportBundleManifestJson",
            str(paths["support"]),
            "-InstalledInventoryJson",
            str(paths["inventory"]),
            "-InstallLifecycleEvidenceJson",
            str(paths["lifecycle"]),
            "-SourceCommitSha",
            env_values["SOURCE_SHA"],
            "-InstallerSha256",
            env_values["INSTALLER_SHA"],
            "-OutputJson",
            str(junction_output / "out.json"),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": env_values["IMMOAPP_TEST_PROGRAMDATA_ROOT"],
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )
    assert result.returncode != 0
    assert "safe_json_output_reparse_point" in (result.stderr + result.stdout)


@pytest.mark.parametrize(
    ("evidence_name", "field", "expected_message"),
    (
        (
            "hub_install",
            "source_commit_sha",
            "Hub install evidence missing required identity field source_commit_sha",
        ),
        (
            "hub_status",
            "installer_sha256",
            "Hub status evidence missing required identity field installer_sha256",
        ),
        (
            "reachability",
            "source_commit_sha",
            "Workstation reachability evidence missing required identity field source_commit_sha",
        ),
        (
            "product",
            "installer_sha256",
            "Workstation product proof evidence missing required identity field installer_sha256",
        ),
    ),
)
def test_hub_beta_m1_verifier_rejects_missing_go_evidence_identity(
    tmp_path: Path,
    evidence_name: str,
    field: str,
    expected_message: str,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    payload = json.loads(paths[evidence_name].read_text(encoding="utf-8"))
    payload.pop(field, None)
    paths[evidence_name].write_text(json.dumps(payload), encoding="utf-8")

    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert expected_message in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_minimal_fake_installed_inventory(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(
        tmp_path,
        inventory_payload={
            "proof_result": "",
            "installed_exe_path": "",
            "installed_exe_sha256": "",
        },
    )
    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "Installed inventory evidence must include proof_result=GO" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_claimed_only_local_installer_hash(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(
        tmp_path,
        inventory_payload={
            "installer_sha256_verified": False,
            "installer_sha256_claimed_only": True,
        },
    )
    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "claimed-only local installer hashes" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_remote_inventory_without_support_hash(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(
        tmp_path,
        inventory_payload={
            "remote_evidence": True,
            "installer_sha256_verified": False,
            "evidence_file_sha256": "2" * 64,
            "installed_inventory_sha256": "3" * 64,
            "support_bundle_sha256": "",
        },
    )
    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "remote evidence/support hashes" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_support_hash_only_without_remote_evidence(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    support = json.loads(paths["support"].read_text(encoding="utf-8"))
    support.pop("bundle_path", None)
    support.pop("support_bundle_path", None)
    support["remote_evidence"] = False
    paths["support"].write_text(json.dumps(support), encoding="utf-8")

    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "local path plus matching hash" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_support_manifest_blank_proof_result(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    support = json.loads(paths["support"].read_text(encoding="utf-8"))
    support["proof_result"] = ""
    paths["support"].write_text(json.dumps(support), encoding="utf-8")

    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "Support bundle manifest evidence must include proof_result=GO" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_remote_support_without_evidence_hash(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    support = json.loads(paths["support"].read_text(encoding="utf-8"))
    support.pop("bundle_path", None)
    support["remote_evidence"] = True
    support["copied_artifact_sha256"] = support["bundle_sha256"]
    support["evidence_file_sha256"] = ""
    paths["support"].write_text(json.dumps(support), encoding="utf-8")

    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "local path plus matching hash" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_remote_support_copied_hash_mismatch(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    support = json.loads(paths["support"].read_text(encoding="utf-8"))
    support.pop("bundle_path", None)
    support.pop("support_bundle_path", None)
    support["remote_evidence"] = True
    support["copied_artifact_sha256"] = "2" * 64
    support["evidence_file_sha256"] = "3" * 64
    paths["support"].write_text(json.dumps(support), encoding="utf-8")

    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "copied_artifact_sha256 must match" in out["failure_reason"]


def test_hub_beta_m1_verifier_accepts_remote_support_with_matching_hashes(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(tmp_path)
    support = json.loads(paths["support"].read_text(encoding="utf-8"))
    support.pop("bundle_path", None)
    support.pop("support_bundle_path", None)
    support["remote_evidence"] = True
    support["copied_artifact_sha256"] = support["bundle_sha256"]
    support["evidence_file_sha256"] = "3" * 64
    paths["support"].write_text(json.dumps(support), encoding="utf-8")

    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode == 0, result.stderr + result.stdout
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    support_phase = next(phase for phase in out["phases"] if phase["name"] == "support_bundle")
    assert support_phase["status"] == "GO"


def test_hub_beta_m1_verifier_rejects_path_only_backup_evidence(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(
        tmp_path,
        backup_payload={"backup_bundle_sha256": ""},
    )
    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "backup_bundle_sha256" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_backup_hash_without_artifact_proof(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(
        tmp_path,
        backup_payload={"backup_bundle_path": ""},
    )
    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert (
        "local backup_bundle_path hash or provide complete remote artifact proof"
        in out["failure_reason"]
    )


def test_hub_beta_m1_verifier_rejects_missing_local_backup_bundle_path(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(
        tmp_path,
        backup_payload={"backup_bundle_path": str(tmp_path / "missing.zip")},
    )
    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "backup_bundle_path is present but does not point" in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_local_backup_hash_mismatch(
    tmp_path: Path,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(
        tmp_path,
        backup_payload={"backup_bundle_sha256": "2" * 64},
    )
    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert "backup_bundle_sha256" in out["failure_reason"]


@pytest.mark.parametrize(
    ("backup_payload", "expected"),
    (
        ({"storage_objects_hash_verified": 0}, "hash-verify every checked storage object"),
        (
            {"live_source_bucket_used_as_restore_target": True},
            "must not use the live source bucket",
        ),
        ({"isolated_restore_bucket": "immoapp"}, "immoapp-restore-drill"),
        ({"restore_database": ""}, "restore_database"),
    ),
)
def test_hub_beta_m1_verifier_rejects_strict_backup_restore_failures(
    tmp_path: Path,
    backup_payload: dict[str, object],
    expected: str,
) -> None:
    paths, env_values = _write_hub_m1_evidence_fixture(
        tmp_path,
        backup_payload=backup_payload,
    )
    result = _run_hub_m1_verifier(tmp_path, paths, env_values)
    assert result.returncode != 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))
    assert expected in out["failure_reason"]


def test_hub_beta_m1_verifier_rejects_wrong_backup_evidence_kind(
    tmp_path: Path,
) -> None:
    verifier = REPO_ROOT / "scripts" / "verify_hub_beta_m1_evidence.ps1"
    source_sha = "a" * 40
    installer_sha = "0" * 64
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    canonical_provider = programdata / "config" / "hub_runtime_provider.json"
    canonical_provider.parent.mkdir(parents=True)

    def write_json(name: str, payload: dict[str, object]) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    runtime_detection = {
        "runtime_dependency_mode": "managed_container_runtime",
        "agency_install_status": "GO",
        "provider_validation_status": "valid",
        "reason_code": "managed_runtime_ready",
        "provider_config_path": str(canonical_provider),
    }
    hub_install = write_json(
        "hub_install.json",
        {
            "kind": "immoapp_hub_install_evidence",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "hub-test",
            "proof_result": "GO",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "runtime_dependency_mode": "managed_container_runtime",
            "agency_install_status": "GO",
            "runtime_detection": runtime_detection,
            "runtime_provider_proof": {"proof_only": False},
            "hub_manager_script_source": "installed",
            "desktop_exe_source": "installed",
            "hub_base_url": "http://192.168.1.10:8000",
            "installed_version": "test",
            "installed_build_identity": {},
        },
    )
    hub_status = write_json(
        "hub_status.json",
        {
            "kind": "immoapp_hub_status_evidence",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "hub-test",
            "proof_result": "GO",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "hub_status": "Online",
            "hub_base_url": "http://192.168.1.10:8000",
            "database_health": "ok",
            "storage_photos_health": "ok",
            "worker_health": "ok",
            "runtime_dependency_mode": "managed_container_runtime",
            "agency_install_status": "GO",
            "runtime_detection": runtime_detection,
            "runtime_provider_proof": {"proof_only": False},
        },
    )
    reachability = write_json(
        "reachability.json",
        {
            "kind": "immoapp_lan_workstation_reachability_proof",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "workstation-test",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "proof_result": "GO",
            "health_status": 200,
            "hub_base_url": "http://192.168.1.10:8000",
        },
    )
    product = write_json(
        "product.json",
        {
            "kind": "immoapp_manual_product_proof_evidence",
            "schema_version": 1,
            "created_at_utc": "2026-01-01T00:00:00Z",
            "machine_name": "workstation-test",
            "source_commit_sha": source_sha,
            "installer_sha256": installer_sha,
            "proof_result": "GO",
            "owner_login_proof": True,
            "create_read_update_proof": True,
            "offer_photo_thumbnail_proof": True,
        },
    )
    backup = write_json(
        "backup.json",
        {
            "kind": "backup_restore",
            "schema_version": 1,
            "proof_result": "GO",
            "restore_database": "immoapp_restore",
            "isolated_restore_bucket": "immoapp-restore-drill-20260101000000-aaaaaaaa",
            "storage_objects_checked": 1,
            "storage_objects_hash_verified": 1,
            "live_source_bucket_used_as_restore_target": False,
            "backup_bundle_sha256": "1" * 64,
        },
    )
    support = write_json("support.json", {"kind": "immoapp_support_bundle_manifest"})
    inventory = write_json(
        "inventory.json",
        {"kind": "immoapp_installed_inventory", "source_commit_sha": source_sha},
    )
    lifecycle = write_json(
        "lifecycle.json",
        {"kind": "immoapp_install_lifecycle_evidence", "proof_result": "GO"},
    )

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(verifier),
            "-HubInstallEvidenceJson",
            str(hub_install),
            "-HubStatusEvidenceJson",
            str(hub_status),
            "-WorkstationReachabilityJson",
            str(reachability),
            "-WorkstationProductProofJson",
            str(product),
            "-BackupRestoreProofJson",
            str(backup),
            "-SupportBundleManifestJson",
            str(support),
            "-InstalledInventoryJson",
            str(inventory),
            "-InstallLifecycleEvidenceJson",
            str(lifecycle),
            "-SourceCommitSha",
            source_sha,
            "-InstallerSha256",
            installer_sha,
            "-OutputJson",
            str(tmp_path / "out.json"),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )
    assert result.returncode != 0
    assert "wrong kind" in (result.stderr + result.stdout)


def test_fresh_machine_lan_docs_are_explicit_no_go_until_proven() -> None:
    checklist = _read("docs/guides/BETA_RELEASE_CHECKLIST.md")
    scripts_readme = _read("scripts/README.md")

    for token in (
        "docs/checklist alone are not proof",
        "installer build GO does not imply fresh-machine GO or LAN GO",
        "missing Git, Inno Setup, a fresh Windows profile/VM, or a second workstation means LAN beta remains NO-GO",
        "support bundle can be collected from workstation",
        "uninstall/reinstall does not destroy Hub data unless explicitly requested",
        "Install ImmoApp Desktop",
        "Set up this computer as Office Hub",
        "Hub Beta Milestone 1 adds the role-aware installer foundation",
        "manual Docker Desktop as a real-agency blocker",
        "desktop backend URL",
        "not `localhost` or `127.0.0.1`",
        "verify_lan_workstation_reachability.ps1",
        "immoapp_hub_install_evidence",
        "immoapp_hub_status_evidence",
        "immoapp_fresh_machine_install_evidence",
        "immoapp_lan_hub_workstation_evidence",
        "Public beta distribution is NO-GO without code signing",
        "{localappdata}\\Programs\\ImmoApp Beta",
        "`_internal` is the Python/PySide6/Qt/native runtime payload",
        "`base_library.zip` is the Python standard-library payload",
        "collect_installed_app_inventory.ps1",
        "collect_install_lifecycle_evidence.ps1",
        "collect_fresh_machine_install_evidence.ps1",
        "write_manual_product_proof_evidence.ps1",
        "collect_lan_workstation_evidence.ps1",
    ):
        assert token in checklist
    assert "complete agency installer" not in checklist.lower()
    assert "run_beta_release_validation.ps1" in scripts_readme
    assert "ReleaseArtifactRoot" in scripts_readme
    assert "AllowReplaceReleaseArtifacts" in scripts_readme
    assert "CleanPreviousValidationArtifacts" in scripts_readme
    assert "verify_lan_workstation_reachability.ps1" in scripts_readme
    assert "collect_installed_app_inventory.ps1" in scripts_readme
    assert "collect_install_lifecycle_evidence.ps1" in scripts_readme
    assert "collect_fresh_machine_install_evidence.ps1" in scripts_readme
    assert "write_manual_product_proof_evidence.ps1" in scripts_readme
    assert "collect_lan_workstation_evidence.ps1" in scripts_readme
    assert "setup_office_hub.ps1" in scripts_readme
    assert "hub_manager.ps1" in scripts_readme
    assert "collect_hub_install_evidence.ps1" in scripts_readme
    assert "collect_hub_status_evidence.ps1" in scripts_readme
    assert "immoapp_installer_package_inventory" in scripts_readme
    assert "desktop_and_or_hub" in scripts_readme
    assert "KeepPyInstallerOutput" in scripts_readme
    assert "InspectBundleOnly" in scripts_readme
    assert "Desktop-only" in scripts_readme
    assert "installer-only" in scripts_readme
    assert "never" in scripts_readme
    assert "repair_local_dev_release_integrity.ps1" in scripts_readme
    assert "called by release validation" in scripts_readme


def test_local_repair_apply_requires_confirmation_and_local_default_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    repair = importlib.import_module("scripts.repair_local_dev_release_integrity")

    repair._assert_apply_allowed(
        apply=False,
        confirmed=False,
        allow_non_default_local_database=False,
        missing_schema=[],
    )
    with pytest.raises(RuntimeError, match="confirm-disposable"):
        repair._assert_apply_allowed(
            apply=True,
            confirmed=False,
            allow_non_default_local_database=False,
            missing_schema=[],
        )

    monkeypatch.setenv("POSTGRES_HOST", "db.example.test")
    monkeypatch.setenv("POSTGRES_DB", "immoapp")
    with pytest.raises(RuntimeError, match="non-local DB host"):
        repair._assert_apply_allowed(
            apply=True,
            confirmed=True,
            allow_non_default_local_database=False,
            missing_schema=[],
        )

    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_DB", "not_immoapp")
    with pytest.raises(RuntimeError, match="non-default local DB"):
        repair._assert_apply_allowed(
            apply=True,
            confirmed=True,
            allow_non_default_local_database=False,
            missing_schema=[],
        )


def test_strict_prod_config_rejects_debug_and_e2e_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")

    def _set_valid() -> None:
        monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "1")
        monkeypatch.setenv("DJANGO_DEBUG", "0")
        monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "0")
        monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE_DOCKER", "0")
        monkeypatch.setenv("IMMOAPP_PUBLIC_BASE_URL", "https://app.example.test")
        monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "app.example.test")
        monkeypatch.setenv("IMMOAPP_TLS_DOMAIN", "app.example.test")
        monkeypatch.setenv("BAO_VERIFY_SSL_DOCKER", "1")
        monkeypatch.setenv("BAO_CACERT_DOCKER", "/run/secrets/openbao-ca.pem")
        monkeypatch.setenv("BAO_ADDR_DOCKER", "https://openbao.example.test:8200")
        monkeypatch.setenv("SECURE_SSL_REDIRECT_DOCKER", "1")
        monkeypatch.setenv("SESSION_COOKIE_SECURE_DOCKER", "1")
        monkeypatch.setenv("CSRF_COOKIE_SECURE_DOCKER", "1")
        monkeypatch.setenv("POSTGRES_ADMIN_PASSWORD", "prod-admin-secret")
        monkeypatch.setenv("POSTGRES_PASSWORD", "prod-app-secret")
        monkeypatch.setenv("RABBITMQ_PASSWORD", "prod-rabbit-secret")

    for name in ("DJANGO_DEBUG", "IMMOAPP_E2E_TEST_MODE", "IMMOAPP_E2E_TEST_MODE_DOCKER"):
        _set_valid()
        monkeypatch.setenv(name, "1")
        with pytest.raises(AssertionError, match=name):
            verify_prod_config._assert_strict_prod_runtime_env()
        monkeypatch.setenv(name, "0")
        verify_prod_config._assert_strict_prod_runtime_env()


def test_preflight_prod_rejects_debug_and_e2e_flags() -> None:
    text = _read("scripts/preflight_prod.ps1")

    assert "function Require-FlagZero" in text
    assert 'Require-FlagZero -Name "DJANGO_DEBUG"' in text
    assert 'Require-FlagZero -Name "IMMOAPP_E2E_TEST_MODE"' in text
    assert 'Require-FlagZero -Name "IMMOAPP_E2E_TEST_MODE_DOCKER"' in text


def test_support_bundle_redacts_config_logs_and_presigned_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path / "appdata"))
    monkeypatch.setenv("IMMOAPP_CLIENT_VERSION", "test-client")

    from app.core_app.paths import config_path, logs_dir
    from app.services import support_bundle

    config_path("client_api.json").write_text(
        json.dumps(
            {
                "base_url": "http://127.0.0.1:1",
                "username": "owner",
                "remember_session": "1",
                "token": "raw-token",
                "password": "raw-password",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("app.log").write_text(
        "Authorization: Bearer abc.def.ghi\n"
        "Authorization: Basic raw-basic\n"
        "Authorization: Token raw-auth-token\n"
        "X-Api-Key: raw-x-api-key\n"
        "X-API-KEY: raw-upper-x-api-key\n"
        "xApiKey: raw-x-camel-api-key\n"
        "api-key: raw-api-key-header\n"
        "url=http://example.test/file?X-Amz-Signature=secret&api_key=raw-query-api-key&token=raw-query-token&ok=1\n"
        "password=raw-password apiKey=raw-api-key token=raw-token "
        "access_token=raw-access refresh_token=raw-refresh client_secret=raw-client-secret\n"
        "accessToken=raw-access-camel refreshToken=raw-refresh-camel idToken=raw-id-token "
        "sessionToken=raw-session-token clientSecret=raw-client-secret-camel xApiKey=raw-x-api-key-kv\n"
        "private_key: raw-private-key-colon certificate: raw-cert-colon signature: raw-signature-colon\n"
        "db-app-role-init-1 | ALTER ROLE immoapp_app WITH PASSWORD 'change-before-start' NOSUPERUSER\n"
        "openbao-init-1 | ready token_file=/run/immoapp-secrets/openbao.token secret_id=raw-secret-id\n"
        "worker-1 | password 'quoted-password'\n"
        '{"password": "json-password", "token": "json-token", "apiKey": "json-api-key", "client_secret": "json-client-secret", "clientSecret": "json-client-secret-camel", "accessToken": "json-access-camel", "certificate": "json-cert"}\n'
        "-----BEGIN PRIVATE KEY-----\nprivate-key-material\n-----END PRIVATE KEY-----\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\nopenssh-key-material\n-----END OPENSSH PRIVATE KEY-----\n"
        "-----BEGIN CERTIFICATE-----\ncertificate-material\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    logs_dir().joinpath("hub_status_evidence.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_status_evidence",
                "schema_version": 1,
                "created_at_utc": "2026-01-01T00:00:00Z",
                "proof_result": "GO",
                "failure_reason": "",
                "hub_status": "Online",
                "runtime_state": "available_managed",
                "compose_state": "running",
                "status_reason_code": "online",
                "hub_base_url": "http://192.168.1.10:8000",
                "hub_address": {"lan_ip": "192.168.1.10", "web_bind_host": "0.0.0.0"},
                "runtime_dependency_mode": "managed_runtime",
                "agency_install_status": "GO",
                "internal_proof_status": "GO",
                "runtime_user_visible": False,
                "transport_security": "local_http_private_lan",
                "database_health": "ok",
                "storage_photos_health": "ok",
                "worker_health": "ok",
                "backup_status": {"status": "present"},
                "runtime_detection": {
                    "kind": "immoapp_hub_runtime_detection",
                    "runtime_dependency_mode": "managed_container_runtime",
                    "agency_install_status": "GO",
                    "internal_proof_status": "GO",
                    "token": "raw-token",
                },
                "runtime_provider_proof": {
                    "provider_config_valid": True,
                    "provider_mode": "managed_container_runtime",
                    "internal_proof_status": "GO",
                },
                "failing_services": [],
                "missing_services": [],
                "starting_services": [],
                "windows_firewall_rule_status": "created",
                "token": "raw-token",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("hub_install_evidence.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_install_evidence",
                "schema_version": 1,
                "created_at_utc": "2026-01-01T00:00:00Z",
                "proof_result": "GO",
                "failure_reason": "",
                "install_role": "hub_desktop",
                "hub_base_url": "http://192.168.1.10:8000",
                "backend_url_is_localhost": False,
                "runtime_dependency_mode": "managed_container_runtime",
                "agency_install_status": "GO",
                "internal_proof_status": "GO",
                "runtime_user_visible": False,
                "runtime_detection": {
                    "kind": "immoapp_hub_runtime_detection",
                    "runtime_dependency_mode": "managed_container_runtime",
                    "agency_install_status": "GO",
                    "password": "raw-password",
                },
                "runtime_provider_proof": {
                    "provider_config_present": True,
                    "provider_config_valid": True,
                    "token": "raw-token",
                },
                "transport_security": "local_http_private_lan",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("hub_runtime_detection.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_runtime_detection",
                "schema_version": 1,
                "created_at_utc": "2026-01-01T00:00:00Z",
                "runtime_dependency_mode": "managed_container_runtime",
                "docker_cli_available": True,
                "docker_engine_reachable": True,
                "docker_desktop_detected": False,
                "compose_available": True,
                "runtime_version": "docker=test",
                "runtime_install_path": "C:/ProgramData/ImmoApp/runtime",
                "runtime_command": "C:/ProgramData/ImmoApp/runtime/bin/runtime.exe",
                "compose_command": "C:/ProgramData/ImmoApp/runtime/bin/runtime.exe",
                "compose_arguments_prefix": ["compose"],
                "runtime_is_user_visible": False,
                "agency_install_status": "GO",
                "internal_proof_status": "GO",
                "runtime_artifact_status": "GO",
                "runtime_start_status": "NO-GO",
                "runtime_start_reason_code": "managed_wsl2_front_door_live_probe_failed",
                "runtime_start_evidence_path": "C:/ProgramData/ImmoApp/logs/managed_wsl2_runtime_start_evidence.json",
                "runtime_start_evidence_sha256": "2" * 64,
                "front_door_health_status": "NO-GO",
                "front_door_live_probe": {
                    "front_door_health_status": "NO-GO",
                    "failure_reason": "probe failed",
                },
                "reason_code": "managed_runtime_ready",
                "reason": "managed",
                "recommended_next_action": "prove LAN",
                "provider_config_path": "C:/ProgramData/ImmoApp/config/hub_runtime_provider.json",
                "provider_config_present": True,
                "provider_config_valid": True,
                "provider_validation_status": "valid",
                "provider_config_error": "",
                "provider": {
                    "secret": "raw-secret",
                    "package_inventory_path": str(
                        logs_dir().joinpath("managed_runtime_package_inventory.json")
                    ),
                },
                "secret": "raw-secret",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("managed_runtime_package_inventory.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_managed_hub_runtime_package_inventory",
                "schema_version": 2,
                "proof_result": "GO",
                "reason_code": "managed_runtime_package_built",
                "package_path": "C:/ProgramData/ImmoApp/runtime/immoapp-managed-runtime.zip",
                "package_sha256": "1" * 64,
                "package_bytes": 128,
                "package_file_count": 1,
                "source_commit_sha": "a" * 40,
                "file_count": 1,
                "total_bytes": 10,
                "critical_executables": {
                    "runtime_executable_relative_path": "bin/runtime.exe",
                    "compose_executable_relative_path": "bin/runtime.exe",
                },
                "forbidden_matches": [],
                "proof_only": False,
                "secret": "raw-secret",
                "apiKey": "raw-api-key",
                "private_key": "raw-private-key",
                ".env": "raw-env",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("hub_network_boundary_evidence.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_network_boundary_evidence",
                "schema_version": 1,
                "created_at_utc": "2026-01-01T00:00:00Z",
                "proof_result": "GO",
                "failure_reason": "",
                "agency_install_status": "GO",
                "reason_code": "boundary_ok",
                "boundary_result": "GO",
                "hub_base_url": "http://192.168.1.10:8000",
                "web_api_health_status": "reachable",
                "web_api_lan_bind_status": "lan_bound",
                "infra_exposure_status": "internal_only",
                "exposed_infra_services": [],
                "firewall_status": "configured",
                "approved_lan_facing_service": "web",
                "approved_lan_facing_port": "8000",
                "infra_ports_policy": "localhost_or_internal_only",
                "unsafe_publishers": [],
                "password": "raw-password",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("managed_wsl2_runtime_candidate_install.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_manager_managed_wsl2_runtime_candidate_install",
                "schema_version": 1,
                "existing_provider_present": True,
                "existing_provider_mode": "managed_container_runtime",
                "existing_provider_preserved": True,
                "candidate_overwrite_refused": True,
                "candidate_registration_status": "NO-GO",
                "runtime_artifact_status": "NO-GO",
                "runtime_start_status": "NO-GO",
                "agency_install_status": "NO_GO",
                "reason_code": "existing_managed_runtime_provider_refuses_candidate_overwrite",
                "runtime_detection": {
                    "runtime_dependency_mode": "managed_wsl2_container_runtime_candidate",
                    "secret": "raw-secret",
                },
                "apiKey": "raw-api-key",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("managed_wsl2_runtime_candidate_remove.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_manager_managed_wsl2_runtime_candidate_remove",
                "schema_version": 1,
                "proof_result": "GO",
                "removed_provider_config": True,
                "removed_runtime_data": False,
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("managed_runtime_log_retention.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_managed_runtime_log_retention_evidence",
                "schema_version": 1,
                "created_at_utc": "2026-01-01T00:00:00Z",
                "proof_result": "GO",
                "reason_code": "managed_runtime_log_retention_go",
                "logs_root": "C:/ProgramData/ImmoApp/logs/managed-runtime",
                "retention_days": 14,
                "max_total_bytes": 536870912,
                "scanned_file_count": 2,
                "deleted_file_count": 1,
                "deleted_bytes": 12,
                "retained_bytes": 24,
                "skipped_file_count": 0,
                "skipped_reasons": [],
                "deleted_files": [{"path": "old.log", "bytes": 12}],
                "agency_install_status": "NO_GO",
                "token": "raw-token",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("managed_wsl2_runtime_logs_evidence.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_managed_wsl2_runtime_logs_evidence",
                "schema_version": 1,
                "proof_result": "GO",
                "log_tail": "ALTER ROLE immoapp_app WITH PASSWORD 'change-before-start' NOSUPERUSER",
                "services": [
                    {
                        "name": "openbao-init",
                        "tail": [
                            "ready token_file=/run/immoapp-secrets/openbao.token",
                            "secret_id=raw-secret-id password 'quoted-password'",
                        ],
                    }
                ],
                "token_file": "/run/immoapp-secrets/openbao.token",
                "secret_id": "raw-secret-id",
            }
        ),
        encoding="utf-8",
    )
    logs_dir().joinpath("hub_owner_authorization.json").write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_owner_authorization_evidence",
                "schema_version": 3,
                "created_at_utc": "2026-01-01T00:00:00Z",
                "expires_at_utc": "2026-01-01T00:05:00Z",
                "proof_result": "GO",
                "owner_authorization_status": "GO",
                "reason_code": "hub_owner_authorization_verified",
                "action": "backup-now",
                "authorization_scope": "hub_manager_protected_action",
                "source": "hub_db",
                "actor_username": "private-owner-name",
                "actor_email": "private-owner@example.test",
                "actor_role": "manager",
                "authorized_role": "agency_owner",
                "evidence_nonce": "raw-owner-evidence-nonce",
                "password": "raw-owner-password",
                "session_token": "raw-owner-session-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        support_bundle,
        "_health_probe",
        lambda base_url, timeout_seconds: {"checked": True, "status": 200},
    )
    from core.runtime.hub_runtime_profile import (
        MachineCapacity,
        resolve_hub_runtime_profile,
        write_hub_runtime_profile,
    )

    ram_bytes = 8 * 1024**3
    write_hub_runtime_profile(
        resolve_hub_runtime_profile(
            capacity=MachineCapacity(
                cpu_count=4,
                total_ram_bytes=ram_bytes,
                available_ram_bytes=ram_bytes,
                total_ram_gb=8,
                available_ram_gb=8,
            )
        )
    )

    bundle_path = support_bundle.create_support_bundle(output_dir=tmp_path / "out")

    with zipfile.ZipFile(bundle_path) as bundle:
        manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
        log_text = bundle.read("logs/app.log").decode("utf-8")
        runtime_logs_evidence = bundle.read(
            "evidence/managed_wsl2_runtime_logs_evidence.json"
        ).decode("utf-8")
        names = set(bundle.namelist())

    assert manifest["client_config"]["username"] == "owner"
    assert manifest["hub_runtime_profile"]["selected_profile"] == "small"
    assert "effective_cpu_budget" in manifest["hub_runtime_profile"]
    assert "pressure" in manifest["hub_runtime_profile"]
    assert manifest["hub_runtime_profile"]["profile_source"] == "persisted_config"
    assert str(manifest["hub_runtime_profile"]["raw_free_ram_diagnostics_only"]) == "True"
    assert manifest["hub_runtime_profile"]["reason"]
    assert "selected_profile_limits" in manifest["hub_runtime_profile"]
    assert manifest["hub_runtime_profile"]["config_path"]
    assert manifest["hub_runtime_profile"]["current_pressure_state"] in {
        "green",
        "yellow",
        "red",
    }
    assert "config/hub_runtime_profile.json" in names
    assert manifest["hub_status_evidence"]["hub_status"] == "Online"
    assert manifest["hub_status_evidence"]["status_reason_code"] == "online"
    assert manifest["hub_status_evidence"]["runtime_dependency_mode"] == "managed_runtime"
    assert manifest["hub_status_evidence"]["windows_firewall_rule_status"] == "created"
    assert manifest["hub_install_evidence"]["install_role"] == "hub_desktop"
    assert manifest["hub_install_evidence"]["runtime_provider_proof"]["provider_config_valid"] in {
        "True",
        True,
    }
    assert (
        manifest["hub_runtime_detection"]["runtime_dependency_mode"] == "managed_container_runtime"
    )
    assert manifest["hub_runtime_detection"]["internal_proof_status"] == "GO"
    assert manifest["hub_runtime_detection"]["runtime_start_status"] == "NO-GO"
    assert (
        manifest["hub_runtime_detection"]["runtime_start_reason_code"]
        == "managed_wsl2_front_door_live_probe_failed"
    )
    assert manifest["hub_runtime_detection"]["front_door_health_status"] == "NO-GO"
    assert (
        manifest["hub_runtime_detection"]["front_door_live_probe"]["front_door_health_status"]
        == "NO-GO"
    )
    assert manifest["hub_runtime_detection"]["reason_code"] == "managed_runtime_ready"
    assert manifest["managed_runtime_package_inventory"]["proof_result"] == "GO"
    assert manifest["managed_runtime_package_inventory"]["reason_code"] == (
        "managed_runtime_package_built"
    )
    assert manifest["managed_wsl2_runtime_artifact_inventory"]["exists"] in {False, "False"}
    assert manifest["managed_wsl2_runtime_bootstrap_evidence"]["exists"] in {False, "False"}
    assert manifest["managed_wsl2_runtime_start_evidence"]["exists"] in {False, "False"}
    assert manifest["managed_wsl2_runtime_status_evidence"]["exists"] in {False, "False"}
    assert manifest["managed_wsl2_runtime_candidate_install"]["candidate_overwrite_refused"] in {
        True,
        "True",
    }
    assert (
        manifest["managed_wsl2_runtime_candidate_install"]["existing_provider_mode"]
        == "managed_container_runtime"
    )
    assert (
        manifest["managed_wsl2_runtime_candidate_install"]["reason_code"]
        == "existing_managed_runtime_provider_refuses_candidate_overwrite"
    )
    assert manifest["managed_wsl2_runtime_candidate_install"]["runtime_artifact_status"] == "NO-GO"
    assert manifest["managed_wsl2_runtime_candidate_remove"]["removed_provider_config"] in {
        True,
        "True",
    }
    assert manifest["managed_runtime_log_retention"]["proof_result"] == "GO"
    assert manifest["managed_runtime_log_retention"]["retention_days"] == "14"
    assert manifest["managed_runtime_log_retention"]["max_total_bytes"] == "536870912"
    assert manifest["managed_runtime_log_retention"]["deleted_file_count"] == "1"
    assert manifest["managed_runtime_log_retention"]["agency_install_status"] == "NO_GO"
    assert manifest["hub_network_boundary_evidence"]["approved_lan_facing_service"] == "web"
    assert manifest["hub_network_boundary_evidence"]["reason_code"] == "boundary_ok"
    assert manifest["hub_network_boundary_evidence"]["infra_exposure_status"] == "internal_only"
    assert manifest["hub_owner_authorization_evidence"]["proof_result"] == "GO"
    assert manifest["hub_owner_authorization_evidence"]["action"] == "backup-now"
    assert "evidence/hub_status_evidence.json" in names
    assert "evidence/hub_install_evidence.json" in names
    assert "evidence/hub_runtime_detection.json" in names
    assert "evidence/managed_wsl2_runtime_candidate_install.json" in names
    assert "evidence/managed_wsl2_runtime_candidate_remove.json" in names
    assert "evidence/managed_runtime_log_retention.json" in names
    assert "evidence/managed_wsl2_runtime_logs_evidence.json" in names
    assert "evidence/managed_wsl2_runtime_artifact_inventory_summary.json" in names
    assert "evidence/managed_wsl2_runtime_bootstrap_evidence.json" not in names
    assert "evidence/hub_network_boundary_evidence.json" in names
    assert "evidence/managed_runtime_package_inventory_summary.json" in names
    assert "raw-token" not in json.dumps(manifest)
    assert "raw-password" not in json.dumps(manifest)
    assert "raw-secret" not in json.dumps(manifest)
    assert "raw-api-key" not in json.dumps(manifest)
    assert "raw-private-key" not in json.dumps(manifest)
    assert "raw-env" not in json.dumps(manifest)
    assert "private-owner-name" not in json.dumps(manifest)
    assert "private-owner@example.test" not in json.dumps(manifest)
    assert "raw-owner-evidence-nonce" not in json.dumps(manifest)
    assert "raw-owner-password" not in json.dumps(manifest)
    assert "raw-owner-session-token" not in json.dumps(manifest)
    assert "raw-password" not in log_text
    assert "raw-api-key" not in log_text
    assert "raw-token" not in log_text
    assert "raw-basic" not in log_text
    assert "raw-auth-token" not in log_text
    assert "raw-x-api-key" not in log_text
    assert "raw-upper-x-api-key" not in log_text
    assert "raw-x-camel-api-key" not in log_text
    assert "raw-api-key-header" not in log_text
    assert "raw-query-api-key" not in log_text
    assert "raw-query-token" not in log_text
    assert "raw-access" not in log_text
    assert "raw-refresh" not in log_text
    assert "raw-client-secret" not in log_text
    assert "raw-access-camel" not in log_text
    assert "raw-refresh-camel" not in log_text
    assert "raw-id-token" not in log_text
    assert "raw-session-token" not in log_text
    assert "raw-client-secret-camel" not in log_text
    assert "raw-x-api-key-kv" not in log_text
    assert "raw-private-key-colon" not in log_text
    assert "raw-cert-colon" not in log_text
    assert "raw-signature-colon" not in log_text
    assert "change-before-start" not in log_text
    assert "/run/immoapp-secrets/openbao.token" not in log_text
    assert "raw-secret-id" not in log_text
    assert "quoted-password" not in log_text
    assert "json-password" not in log_text
    assert "json-token" not in log_text
    assert "json-api-key" not in log_text
    assert "json-client-secret" not in log_text
    assert "json-client-secret-camel" not in log_text
    assert "json-access-camel" not in log_text
    assert "json-cert" not in log_text
    assert "private-key-material" not in log_text
    assert "openssh-key-material" not in log_text
    assert "certificate-material" not in log_text
    assert "Bearer [REDACTED]" in log_text
    assert "Authorization: Basic [REDACTED]" in log_text
    assert "Authorization: Token [REDACTED]" in log_text
    assert "X-Api-Key: [REDACTED]" in log_text
    assert "X-API-KEY: [REDACTED]" in log_text
    assert "xApiKey: [REDACTED]" in log_text
    assert "api-key: [REDACTED]" in log_text
    assert "X-Amz-Signature=[REDACTED]" in log_text
    assert "api_key=[REDACTED]" in log_text
    assert "token=[REDACTED]" in log_text
    assert "password=[REDACTED]" in log_text
    assert "apiKey=[REDACTED]" in log_text
    assert "token=[REDACTED]" in log_text
    assert "access_token=[REDACTED]" in log_text
    assert "refresh_token=[REDACTED]" in log_text
    assert "client_secret=[REDACTED]" in log_text
    assert "accessToken=[REDACTED]" in log_text
    assert "refreshToken=[REDACTED]" in log_text
    assert "idToken=[REDACTED]" in log_text
    assert "sessionToken=[REDACTED]" in log_text
    assert "clientSecret=[REDACTED]" in log_text
    assert "xApiKey=[REDACTED]" in log_text
    assert "private_key: [REDACTED]" in log_text
    assert "certificate: [REDACTED]" in log_text
    assert "signature: [REDACTED]" in log_text
    assert "WITH PASSWORD '[REDACTED]'" in log_text
    assert "token_file=[REDACTED]" in log_text
    assert "secret_id=[REDACTED]" in log_text
    assert "password '[REDACTED]'" in log_text
    assert '"password": "[REDACTED]"' in log_text
    assert '"token": "[REDACTED]"' in log_text
    assert '"apiKey": "[REDACTED]"' in log_text
    assert '"client_secret": "[REDACTED]"' in log_text
    assert '"clientSecret": "[REDACTED]"' in log_text
    assert '"accessToken": "[REDACTED]"' in log_text
    assert '"certificate": "[REDACTED]"' in log_text
    assert "[REDACTED PRIVATE KEY]" in log_text
    assert "[REDACTED CERTIFICATE]" in log_text
    assert "change-before-start" not in runtime_logs_evidence
    assert "/run/immoapp-secrets/openbao.token" not in runtime_logs_evidence
    assert "raw-secret-id" not in runtime_logs_evidence
    assert "quoted-password" not in runtime_logs_evidence
    assert "WITH PASSWORD '[REDACTED]'" in runtime_logs_evidence
    assert "token_file=[REDACTED]" in runtime_logs_evidence
    assert "secret_id" in runtime_logs_evidence
    assert "[REDACTED]" in runtime_logs_evidence
