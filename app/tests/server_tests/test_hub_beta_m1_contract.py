from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# This module exercises Hub/managed-runtime proof behavior through many
# PowerShell subprocesses and fake runtime bridges. Keep it in full/release
# gates, but out of the PR lane so PR remains a fast feedback gate.
pytestmark = pytest.mark.slow


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _run_powershell(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        check=check,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=timeout,
    )


def _stop_processes_with_command_fragment(fragment: Path) -> None:
    resolved = fragment.resolve()
    windows_needle = str(resolved).replace("'", "''")
    posix = resolved.as_posix()
    drive = resolved.drive.rstrip(":").lower()
    git_sh_needle = (f"/{drive}{posix[2:]}" if drive else posix).replace("'", "''")
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                f"$needles = @('{windows_needle}', '{git_sh_needle}'); $self = $PID; "
                "Get-CimInstance Win32_Process | "
                "Where-Object { "
                "$cmd = $_.CommandLine; "
                "$matched = $false; "
                "foreach ($needle in $needles) { if ($needle -and $cmd -and $cmd.Contains($needle)) { $matched = $true; break } }; "
                "$_.ProcessId -ne $self -and $cmd -and $matched "
                "} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _write_fake_runtime(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "@echo off\r\n"
        'if "%1"=="version" echo 29.0.0& exit /b 0\r\n'
        'if "%1"=="compose" echo v5.1.0& exit /b 0\r\n'
        "exit /b 0\r\n",
        encoding="utf-8",
    )


def _write_marker_runtime(path: Path, marker: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "@echo off\r\n"
        f'echo executed>"{marker}"\r\n'
        'if "%1"=="version" echo 29.0.0& exit /b 0\r\n'
        'if "%1"=="compose" echo v5.1.0& exit /b 0\r\n'
        "exit /b 0\r\n",
        encoding="utf-8",
    )


def _write_runtime_zip(artifact: Path, source: Path) -> None:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(source).as_posix())


def _write_managed_provider_fixture(
    tmp_path: Path,
    *,
    provider_overrides: dict[str, object] | None = None,
    inventory_overrides: dict[str, object] | None = None,
    runtime_path: Path | None = None,
) -> tuple[Path, dict[str, str], dict[str, Path]]:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    runtime_root = programdata / "runtime"
    data_root = programdata / "data"
    logs_root = programdata / "logs"
    config_root = programdata / "config"
    for path in (runtime_root, data_root, logs_root, config_root):
        path.mkdir(parents=True, exist_ok=True)

    runtime = runtime_path or (runtime_root / "immoapp-runtime.cmd")
    _write_fake_runtime(runtime)
    try:
        runtime_relative = runtime.relative_to(runtime_root).as_posix()
    except ValueError:
        runtime_relative = runtime.name
    runtime_sha = _sha256(runtime)

    package = runtime_root / "immoapp-managed-runtime.zip"
    package.write_bytes(b"managed-runtime-package")
    package_sha = _sha256(package)
    source_sha = "a" * 40
    inventory_payload: dict[str, object] = {
        "kind": "immoapp_managed_hub_runtime_package_inventory",
        "schema_version": 2,
        "created_at_utc": "2026-01-01T00:00:00Z",
        "proof_result": "GO",
        "reason_code": "managed_runtime_package_built",
        "package_path": str(package),
        "package_sha256": package_sha,
        "package_bytes": package.stat().st_size,
        "package_file_count": 1,
        "file_count": 1,
        "total_bytes": runtime.stat().st_size,
        "proof_only": False,
        "source_tree_clean": True,
        "source_commit_override": False,
        "runtime_source_origin": "repo",
        "dirty_files_summary_count": 0,
        "critical_executables": {
            "runtime_executable_relative_path": runtime_relative,
            "compose_executable_relative_path": runtime_relative,
        },
        "forbidden_matches": [],
        "source_commit_sha": source_sha,
        "files": [
            {
                "path": runtime_relative,
                "bytes": runtime.stat().st_size,
                "sha256": runtime_sha,
            }
        ],
    }
    if inventory_overrides:
        inventory_payload.update(inventory_overrides)
    inventory = config_root / "managed_hub_runtime_package_inventory.json"
    inventory.write_text(json.dumps(inventory_payload), encoding="utf-8")

    provider_payload: dict[str, object] = {
        "kind": "immoapp_hub_runtime_provider",
        "schema_version": 1,
        "provider_mode": "managed_container_runtime",
        "installed_by_immoapp": True,
        "user_visible_runtime": False,
        "proof_only": False,
        "runtime_executable_path": str(runtime),
        "compose_mode": "docker_cli_plugin",
        "runtime_version": "test",
        "install_root": str(runtime_root),
        "data_root": str(data_root),
        "logs_root": str(logs_root),
        "managed_service_name": "ImmoAppHubRuntime",
        "created_at_utc": "2026-01-01T00:00:00Z",
        "source_commit_sha": source_sha,
        "installer_sha256": "0" * 64,
        "package_sha256": package_sha,
        "package_inventory_path": str(inventory),
    }
    if provider_overrides:
        provider_payload.update(provider_overrides)
    provider = config_root / "hub_runtime_provider.json"
    provider.write_text(json.dumps(provider_payload), encoding="utf-8")

    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_ALLOW_TEST_OWNER_AUTHORIZATION_CONFIRMATION": "1",
    }
    paths = {
        "programdata": programdata,
        "runtime_root": runtime_root,
        "data_root": data_root,
        "logs_root": logs_root,
        "config_root": config_root,
        "runtime": runtime,
        "package": package,
        "inventory": inventory,
    }
    return provider, env, paths


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hub_state_test_env(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_ALLOW_TEST_OWNER_AUTHORIZATION_CONFIRMATION": "1",
    }
    return programdata, env


def _run_hub_setup(
    programdata: Path, env: dict[str, str], name: str = "Main Office"
) -> dict[str, Any]:
    output = programdata / "logs" / "hub_setup.json"
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "setup_office_hub.ps1"),
            "-DataRoot",
            str(programdata),
            "-HubDisplayName",
            name,
            "-NoLanAccess",
            "-NoAutoStart",
            "-NoStartHub",
            "-NoShortcuts",
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )
    assert result.returncode == 0
    return cast(dict[str, Any], json.loads(output.read_text(encoding="utf-8-sig")))


def _write_minimal_hub_identity_state(programdata: Path) -> None:
    config_root = programdata / "config"
    data_root = programdata / "data"
    runtime_root = programdata / "runtime"
    logs_root = programdata / "logs"
    for root in (config_root, data_root, runtime_root, logs_root):
        root.mkdir(parents=True, exist_ok=True)
    identity_path = config_root / "hub_identity.json"
    state_path = config_root / "hub_state_manifest.json"
    if identity_path.exists() and state_path.exists():
        return
    hub_id = hashlib.sha256(str(programdata).encode("utf-8")).hexdigest()[:32]
    identity_path.write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_identity",
                "schema_version": 1,
                "hub_id": hub_id,
                "hub_display_name": "Main Office",
                "friendly_name": "Main Office",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "updated_at_utc": "2026-01-01T00:00:00Z",
                "created_by_source": "dev_fixture",
                "updated_by_source": "dev_fixture",
                "created_by_windows_user": "test",
                "updated_by_windows_user": "test",
                "machine_hostname_readonly": "test-host",
                "source": "dev_fixture",
            }
        ),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_state_manifest",
                "schema_version": 1,
                "hub_id": hub_id,
                "hub_display_name": "Main Office",
                "friendly_name": "Main Office",
                "config_root": str(config_root),
                "data_root": str(data_root),
                "runtime_root": str(runtime_root),
                "logs_root": str(logs_root),
                "install_lineage": "test-install-lineage",
                "runtime_provider_mode": "",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "updated_at_utc": "2026-01-01T00:00:00Z",
                "created_by_source": "dev_fixture",
                "updated_by_source": "dev_fixture",
                "machine_hostname_readonly": "test-host",
            }
        ),
        encoding="utf-8",
    )


def _write_owner_delete_evidence(
    programdata: Path,
    *,
    role: str = "agency_owner",
    actor_role: str = "manager",
    actor_is_owner: bool = True,
    actor_can_hard_delete: bool = False,
    action: str = "delete_hub_data",
    created_at_utc: str | None = None,
    expires_at_utc: str | None = None,
    hub_id_override: str | None = None,
    state_hash_override: str | None = None,
    authorization_scope: str | None = None,
) -> Path:
    identity_path = programdata / "config" / "hub_identity.json"
    state_path = programdata / "config" / "hub_state_manifest.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8-sig"))
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    now = datetime.now(UTC).replace(microsecond=0)
    created_at_utc = created_at_utc or now.isoformat()
    expires_at_utc = expires_at_utc or (now + timedelta(minutes=10)).isoformat()
    payload = {
        "kind": "immoapp_hub_owner_authorization_evidence",
        "schema_version": 3,
        "created_at_utc": created_at_utc,
        "expires_at_utc": expires_at_utc,
        "proof_result": "GO",
        "owner_authorization_status": "GO",
        "reason_code": "hub_owner_authorization_verified",
        "action": action,
        "authorization_scope": authorization_scope
        or ("hub_data_delete" if action == "delete_hub_data" else "hub_manager_protected_action"),
        "source": "hub_db",
        "evidence_nonce": "contract-test-owner-authorization-nonce-0001",
        "actor_user_id": 1,
        "actor_username": "owner",
        "actor_role": actor_role,
        "actor_is_owner": actor_is_owner,
        "actor_can_hard_delete": actor_can_hard_delete,
        "actor_is_superuser": False,
        "authorized_role": role,
        "hub_id": hub_id_override or identity["hub_id"],
        "hub_identity_sha256": _sha256(identity_path),
        "hub_state_manifest_sha256": state_hash_override or _sha256(state_path),
        "hub_state_install_lineage": state["install_lineage"],
        "password_hash_present": True,
        "password_hash_algorithm": "pbkdf2_sha256",
        "plaintext_password_written": False,
        "session_token_written": False,
        "test_confirmation_status": "GO",
        "agency_install_status": "NO_GO",
        "public_beta_status": "NO_GO",
    }
    path = programdata / "logs" / "owner_authorization.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_hub_manager_owner_evidence(programdata: Path, action: str) -> Path:
    _write_minimal_hub_identity_state(programdata)
    return _write_owner_delete_evidence(programdata, action=action)


def _hub_manager_owner_evidence_args(
    programdata: Path,
    env: dict[str, str],
    action: str,
) -> list[str]:
    env["IMMOAPP_ALLOW_TEST_OWNER_AUTHORIZATION_CONFIRMATION"] = "1"
    evidence = _write_hub_manager_owner_evidence(programdata, action)
    return ["-OwnerAuthorizationEvidenceJson", str(evidence)]


def _hub_manager_install_runtime_artifact_args(
    programdata: Path, *, output_json: Path | None = None
) -> list[str]:
    owner_evidence = _write_hub_manager_owner_evidence(
        programdata,
        "install-runtime-artifact",
    )
    args = [
        "-File",
        str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
        "-Action",
        "install-runtime-artifact",
        "-ConfirmInstallRuntimeArtifact",
        "-MachineTotalMemoryGb",
        "16",
        "-MachineLogicalProcessors",
        "8",
        "-OwnerAuthorizationEvidenceJson",
        str(owner_evidence),
    ]
    if output_json is not None:
        args.extend(["-OutputJson", str(output_json)])
    return args


MANAGED_WSL2_ROOTFS_REQUIRED_ENTRIES = (
    "opt/immoapp/runtime/bin/immoapp-runtime-identity",
    "opt/immoapp/runtime/bin/start-managed-hub",
    "opt/immoapp/runtime/bin/status-managed-hub",
    "opt/immoapp/runtime/bin/health-managed-hub",
    "opt/immoapp/runtime/bin/logs-managed-hub",
    "opt/immoapp/runtime/bin/backup-managed-hub",
    "opt/immoapp/runtime/bin/stop-managed-hub",
    "opt/immoapp/runtime/bin/restart-managed-hub",
    "opt/immoapp/runtime/bin/keepalive-managed-hub",
    "opt/immoapp/runtime/compose/compose.yaml",
)

MANAGED_LOCAL_IMAGE_TAGS = (
    "immoapp-managed/busybox:1.36",
    "immoapp-managed/postgis:18-3.6",
    "immoapp-managed/rabbitmq:3.13-management",
    "immoapp-managed/valkey:9.0.1",
    "immoapp-managed/openbao:2.3.1",
    "immoapp-managed/minio:RELEASE.2025-09-07T16-13-09Z",
    "immoapp-managed/minio-mc:RELEASE.2025-08-13T08-35-41Z",
    "immoapp-managed/clamav:1.4.3",
    "immoapp-managed/server:local",
    "immoapp-managed/caddy:2.9.1",
)


def test_hub_setup_creates_identity_and_state_manifest(tmp_path: Path) -> None:
    programdata, env = _hub_state_test_env(tmp_path)

    evidence = _run_hub_setup(programdata, env)

    identity = json.loads(
        (programdata / "config" / "hub_identity.json").read_text(encoding="utf-8-sig")
    )
    manifest = json.loads(
        (programdata / "config" / "hub_state_manifest.json").read_text(encoding="utf-8-sig")
    )
    assert evidence["hub_identity_status"] == "GO"
    assert evidence["hub_state_manifest_status"] == "GO"
    assert identity["kind"] == "immoapp_hub_identity"
    assert identity["hub_id"]
    assert identity["friendly_name"] == "Main Office"
    assert manifest["kind"] == "immoapp_hub_state_manifest"
    assert manifest["hub_id"] == identity["hub_id"]
    assert manifest["data_root"] == str(programdata / "data")
    assert "password" not in json.dumps(manifest).lower()


def test_hub_setup_rerun_preserves_hub_id_and_install_lineage(tmp_path: Path) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env, "Main Office")
    identity_before = json.loads(
        (programdata / "config" / "hub_identity.json").read_text(encoding="utf-8-sig")
    )
    manifest_before = json.loads(
        (programdata / "config" / "hub_state_manifest.json").read_text(encoding="utf-8-sig")
    )

    _run_hub_setup(programdata, env, "Main Office")

    identity_after = json.loads(
        (programdata / "config" / "hub_identity.json").read_text(encoding="utf-8-sig")
    )
    manifest_after = json.loads(
        (programdata / "config" / "hub_state_manifest.json").read_text(encoding="utf-8-sig")
    )
    assert identity_after["hub_id"] == identity_before["hub_id"]
    assert manifest_after["hub_id"] == manifest_before["hub_id"]
    assert manifest_after["install_lineage"] == manifest_before["install_lineage"]


def test_hub_rename_updates_identity_and_state_manifest(tmp_path: Path) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env, "Main Office")
    identity_before = json.loads(
        (programdata / "config" / "hub_identity.json").read_text(encoding="utf-8-sig")
    )

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "set_hub_identity.ps1"),
            "-HubDisplayName",
            "Reception Office",
            "-Source",
            "hub_manager",
        ],
        env=env,
        check=False,
    )

    evidence = json.loads(result.stdout)
    identity_after = json.loads(
        (programdata / "config" / "hub_identity.json").read_text(encoding="utf-8-sig")
    )
    manifest_after = json.loads(
        (programdata / "config" / "hub_state_manifest.json").read_text(encoding="utf-8-sig")
    )
    assert evidence["hub_identity_status"] == "GO"
    assert evidence["hub_state_manifest_status"] == "GO"
    assert identity_after["hub_id"] == identity_before["hub_id"]
    assert manifest_after["hub_id"] == identity_before["hub_id"]
    assert identity_after["friendly_name"] == "Reception Office"
    assert manifest_after["friendly_name"] == "Reception Office"


def test_hub_setup_refuses_mismatched_existing_manifest(tmp_path: Path) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    manifest_path = programdata / "config" / "hub_state_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["hub_id"] = "wrong-hub-id"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "setup_office_hub.ps1"),
            "-DataRoot",
            str(programdata),
            "-HubDisplayName",
            "Main Office",
            "-NoLanAccess",
            "-NoAutoStart",
            "-NoStartHub",
            "-NoShortcuts",
            "-OutputJson",
            str(programdata / "logs" / "rerun.json"),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "hub_state_manifest_identity_mismatch" in (result.stderr + result.stdout)


def test_hub_data_delete_requires_confirmation_owner_and_admin(tmp_path: Path) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    output = programdata / "logs" / "delete.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "delete-hub-data",
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    evidence = json.loads(output.read_text(encoding="utf-8-sig"))
    assert evidence["proof_result"] == "NO-GO"
    assert evidence["reason_code"] == "hub_delete_confirm_flag_required"
    assert (programdata / "config" / "hub_identity.json").exists()


def test_hub_data_delete_succeeds_only_with_owner_admin_and_confirmation(
    tmp_path: Path,
) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    owner_evidence = _write_owner_delete_evidence(programdata)
    env = {**env, "IMMOAPP_TEST_ASSUME_WINDOWS_ADMIN": "1"}
    output = programdata / "logs" / "delete.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "delete-hub-data",
            "-ConfirmDeleteHubData",
            "-TypedConfirmation",
            "DELETE HUB DATA",
            "-OwnerAuthorizationEvidenceJson",
            str(owner_evidence),
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode == 0
    evidence = json.loads(output.read_text(encoding="utf-8-sig"))
    assert evidence["proof_result"] == "GO"
    assert not (programdata / "config").exists()
    assert not (programdata / "data").exists()
    assert not (programdata / "runtime").exists()
    assert (programdata / "logs").exists()


@pytest.mark.parametrize(
    ("env_override", "typed_confirmation", "reason_code"),
    [
        (
            {"IMMOAPP_TEST_ASSUME_WINDOWS_ADMIN": "1"},
            "delete hub data",
            "hub_delete_confirmation_text_required",
        ),
        ({}, "DELETE HUB DATA", "hub_delete_windows_admin_required"),
    ],
)
def test_hub_data_delete_rejects_missing_admin_or_wrong_typed_confirmation(
    tmp_path: Path,
    env_override: dict[str, str],
    typed_confirmation: str,
    reason_code: str,
) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    owner_evidence = _write_owner_delete_evidence(programdata)
    env = {**env, **env_override}
    output = programdata / "logs" / "delete.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "delete-hub-data",
            "-ConfirmDeleteHubData",
            "-TypedConfirmation",
            typed_confirmation,
            "-OwnerAuthorizationEvidenceJson",
            str(owner_evidence),
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    evidence = json.loads(output.read_text(encoding="utf-8-sig"))
    assert evidence["proof_result"] == "NO-GO"
    assert evidence["reason_code"] == reason_code
    assert (programdata / "config" / "hub_identity.json").exists()
    assert (programdata / "data").exists()


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        (
            {"role": "agency_employee", "actor_role": "agent", "actor_is_owner": False},
            "hub_delete_owner_authorization_role_invalid",
        ),
        ({"action": "rename_hub"}, "hub_delete_owner_authorization_action_invalid"),
        (
            {
                "created_at_utc": "2026-01-01T00:00:00+00:00",
                "expires_at_utc": "2026-01-01T00:10:00+00:00",
            },
            "hub_delete_owner_authorization_expired",
        ),
        ({"hub_id_override": "wrong-hub"}, "hub_delete_owner_authorization_hub_mismatch"),
        ({"state_hash_override": "0" * 64}, "hub_delete_owner_authorization_state_hash_mismatch"),
    ],
)
def test_hub_data_delete_rejects_invalid_owner_authorization_evidence(
    tmp_path: Path, overrides: dict[str, Any], reason_code: str
) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    owner_evidence = _write_owner_delete_evidence(programdata, **overrides)
    env = {**env, "IMMOAPP_TEST_ASSUME_WINDOWS_ADMIN": "1"}
    output = programdata / "logs" / "delete.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "delete-hub-data",
            "-ConfirmDeleteHubData",
            "-TypedConfirmation",
            "DELETE HUB DATA",
            "-OwnerAuthorizationEvidenceJson",
            str(owner_evidence),
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    evidence = json.loads(output.read_text(encoding="utf-8-sig"))
    assert evidence["proof_result"] == "NO-GO"
    assert evidence["reason_code"] == reason_code
    assert (programdata / "config" / "hub_identity.json").exists()
    assert (programdata / "data").exists()


def test_hub_data_delete_rejects_malformed_owner_authorization_evidence(
    tmp_path: Path,
) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    owner_evidence = programdata / "logs" / "owner_authorization.json"
    owner_evidence.parent.mkdir(parents=True, exist_ok=True)
    owner_evidence.write_text("{", encoding="utf-8")
    env = {**env, "IMMOAPP_TEST_ASSUME_WINDOWS_ADMIN": "1"}
    output = programdata / "logs" / "delete.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "delete-hub-data",
            "-ConfirmDeleteHubData",
            "-TypedConfirmation",
            "DELETE HUB DATA",
            "-OwnerAuthorizationEvidenceJson",
            str(owner_evidence),
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    evidence = json.loads(output.read_text(encoding="utf-8-sig"))
    assert evidence["proof_result"] == "NO-GO"
    assert evidence["reason_code"] == "hub_delete_owner_authorization_malformed_json"
    assert (programdata / "config" / "hub_identity.json").exists()
    assert (programdata / "data").exists()


def test_hub_data_delete_rejects_when_runtime_stop_fails(tmp_path: Path) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    owner_evidence = _write_owner_delete_evidence(programdata)
    env = {**env, "IMMOAPP_TEST_ASSUME_WINDOWS_ADMIN": "1"}
    copied_scripts = tmp_path / "copied_scripts"
    copied_scripts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "common.ps1", copied_scripts / "common.ps1")
    shutil.copy2(REPO_ROOT / "scripts" / "hub_manager.ps1", copied_scripts / "hub_manager.ps1")
    shutil.copy2(
        REPO_ROOT / "scripts" / "hub_manager_authorization.ps1",
        copied_scripts / "hub_manager_authorization.ps1",
    )
    (copied_scripts / "detect_hub_runtime.ps1").write_text(
        """
param([string]$OutputJson = "")
$payload = [ordered]@{
  kind = "immoapp_hub_runtime_detection"
  schema_version = 1
  runtime_start_status = "GO"
  front_door_health_status = "GO"
  agency_install_status = "NO_GO"
}
if ($OutputJson) {
  $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
}
$payload | ConvertTo-Json -Depth 5
""",
        encoding="utf-8",
    )
    output = programdata / "logs" / "delete.json"

    result = _run_powershell(
        [
            "-File",
            str(copied_scripts / "hub_manager.ps1"),
            "-Action",
            "delete-hub-data",
            "-ConfirmDeleteHubData",
            "-TypedConfirmation",
            "DELETE HUB DATA",
            "-OwnerAuthorizationEvidenceJson",
            str(owner_evidence),
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    evidence = json.loads(output.read_text(encoding="utf-8-sig"))
    assert evidence["reason_code"] == "hub_delete_runtime_stop_failed"
    assert (programdata / "config" / "hub_identity.json").exists()
    assert (programdata / "data").exists()


def test_hub_preserved_data_state_detects_identity_manifest_data_and_database(
    tmp_path: Path,
) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    pg_marker = programdata / "data" / "pgdata" / "PG_VERSION"
    pg_marker.parent.mkdir(parents=True, exist_ok=True)
    pg_marker.write_text("18", encoding="utf-8")
    output = programdata / "logs" / "install_evidence.json"

    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "collect_hub_install_evidence.ps1"),
            "-InstallRole",
            "hub_only",
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    evidence = json.loads(output.read_text(encoding="utf-8-sig"))
    assert evidence["proof_result"] == "NO-GO"
    preserved = evidence["preserved_hub_data_state"]
    assert preserved["proof_result"] == "GO"
    assert preserved["hub_identity_present"] is True
    assert preserved["hub_state_manifest_present"] is True
    assert preserved["data_root_present"] is True
    assert preserved["database_state_present"] is True


def test_desktop_tokens_use_keyring_without_plaintext_fallback() -> None:
    auth = _read("app/services/api_client_auth.py")

    assert "keyring.set_password" in auth
    assert "keyring.get_password" in auth
    assert "using in-memory token persistence" in auth
    assert "write_text" not in auth
    assert "open(" not in auth


def test_owner_authorization_generator_uses_hub_front_door_without_secret_cli() -> None:
    source = _read("scripts/create_hub_owner_authorization_evidence.py")

    assert "request_owner_authorization" in source
    assert "--base-url" in source
    assert "--password-stdin" in source
    assert "--password-env" in source
    assert "password_value" in source
    assert '--password"' not in source
    assert "_approved_output_path" in source
    assert "hub_owner_authorization_output_path_unapproved" in source
    assert "plaintext_password_written" in source
    assert "session_token_written" in source
    assert "hub_identity_sha256" in source
    assert "hub_state_manifest_sha256" in source
    assert "get_user_model" not in source
    assert "django.setup" not in source
    build = _read("scripts/build_desktop_installer.ps1")
    assert '"scripts.create_hub_owner_authorization_evidence"' in build
    assert '"app.services.hub_manager_access_client"' in build
    assert '"server.immoapp_server.settings"' not in build
    assert '"server.accounts.models"' not in build
    assert "[string]$ManagedWslArtifactRoot" in build
    assert "[string]$ManagedWslArtifactInventoryPath" in build
    assert "-ExpectedSourceCommitSha $gitShaFull" in build
    assert (
        "Managed WSL2 runtime artifact inventory source commit does not match "
        "installer source commit." in build
    )


def test_hub_manager_protected_powershell_action_requires_owner_evidence(
    tmp_path: Path,
) -> None:
    programdata, env = _hub_state_test_env(tmp_path)
    _run_hub_setup(programdata, env)
    output = programdata / "logs" / "backup_blocked.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "backup-now",
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["kind"] == "immoapp_hub_manager_owner_authorization"
    assert payload["proof_result"] == "NO-GO"
    assert payload["protected_action_blocked"] is True
    assert payload["action"] == "backup-now"
    assert payload["reason_code"] == "hub_delete_owner_authorization_required"


def test_installer_uninstall_preserves_hub_data_by_default() -> None:
    installer = _read("deployment/installer/ImmoAppBeta.iss")

    assert "[UninstallDelete]" in installer
    assert 'Type: filesandordirs; Name: "{app}\\core\\__pycache__"' in installer
    assert 'Type: filesandordirs; Name: "{app}\\core\\runtime\\__pycache__"' in installer
    assert 'Type: files; Name: "{app}\\core\\*.pyc"' in installer
    assert 'Type: files; Name: "{app}\\core\\runtime\\*.pyc"' in installer
    assert 'Type: files; Name: "{app}\\is-*.tmp"' in installer
    assert 'Type: files; Name: "{app}\\_internal\\PySide6\\is-*.tmp"' in installer
    assert 'Type: files; Name: "{app}\\deployment\\managed-runtime\\images\\is-*.tmp"' in installer
    assert "procedure DeleteInstallerTempFiles(Directory: String);" in installer
    assert "DeleteInstallerTempFiles(ExpandConstant('{app}'));" in installer
    assert "CleanInstallRootGeneratedLeftovers();" in installer
    assert "AddBackslash(Directory) + 'is-*.tmp'" in installer
    assert 'Type: files; Name: "{app}\\deployment\\managed-runtime\\*"' not in installer
    assert 'Type: files; Name: "{app}\\scripts\\*"' not in installer
    assert "DelTree(" not in installer
    assert "RemoveDir(" not in installer
    assert "data_preserved_on_uninstall" in _read("scripts/collect_hub_install_evidence.ps1")
    assert "full_data_wipe_requires_separate_confirmation" in _read(
        "scripts/collect_hub_install_evidence.ps1"
    )


def test_support_bundle_includes_sanitized_hub_state_manifest() -> None:
    support = _read("app/services/support_bundle.py")

    assert "_read_hub_state_manifest_summary" in support
    assert '"hub_state_manifest": _read_hub_state_manifest_summary()' in support
    assert "_read_hub_owner_authorization_summary" in support
    assert '"hub_owner_authorization_evidence": _read_hub_owner_authorization_summary()' in support
    assert "_NON_SECRET_AUTH_SUMMARY_KEYS" in support
    assert "_read_hub_delete_approval_summary" in support
    assert '"hub_delete_approval_evidence": _read_hub_delete_approval_summary()' in support
    assert "actor_email" not in support
    assert "actor_username" not in support
    assert "_sanitize_mapping" in support


def test_installed_support_bundle_has_no_repo_source_dependency() -> None:
    script = _read("scripts/collect_desktop_support_bundle.ps1")

    assert 'Join-Path (Get-ImmoAppRepoRoot) "app\\services\\support_bundle.py"' in script
    assert "New-ImmoAppInstalledSupportBundle -OutputDir $OutputDir" in script
    assert 'collector = "installed_powershell_fallback"' in script
    assert "System.IO.Compression.ZipArchive" in script
    assert "ConvertTo-ImmoAppSupportSanitizedObject" in script
    assert "ConvertTo-ImmoAppSupportRedactedText" in script
    assert "bundle_sha256" in script
    assert "support_bundle_sha256" in script


def _write_fake_managed_image_bundle(
    programdata: Path,
    *,
    archive_bytes: bytes = b"fake-managed-runtime-image-archive",
) -> tuple[Path, str, Path, str]:
    archive = programdata / "runtime" / "images" / "immoapp-runtime-images.tar"
    inventory = programdata / "config" / "managed_wsl2_runtime_image_bundle_inventory.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    inventory.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(archive_bytes)
    archive_sha = _sha256(archive)
    inventory_payload = {
        "kind": "immoapp_managed_wsl2_runtime_image_bundle_inventory",
        "schema_version": 1,
        "created_at_utc": "2026-01-01T00:00:00Z",
        "source_commit_sha": "a" * 40,
        "app_image_source_commit_sha": "a" * 40,
        "app_image_revision_label": "org.opencontainers.image.revision",
        "app_image_revision_verified": True,
        "image_archive_path": str(archive),
        "image_archive_host_path": str(archive),
        "image_archive_wsl_path": "/mnt/c/ProgramData/ImmoApp/runtime/images/immoapp-runtime-images.tar",
        "image_archive_sha256": archive_sha,
        "image_archive_bytes": archive.stat().st_size,
        "image_bundle_inventory_host_path": str(inventory),
        "image_bundle_inventory_wsl_path": (
            "/mnt/c/ProgramData/ImmoApp/config/" "managed_wsl2_runtime_image_bundle_inventory.json"
        ),
        "image_count": len(MANAGED_LOCAL_IMAGE_TAGS),
        "images": [
            {"service": tag.rsplit("/", 1)[-1], "source_image": tag, "tag": tag}
            for tag in MANAGED_LOCAL_IMAGE_TAGS
        ],
        "docker_pull_invoked": False,
        "package_manager_install_invoked": False,
        "compose_pull_policy_required": "never",
        "proof_result": "GO",
        "reason_code": "managed_runtime_image_bundle_built",
        "agency_install_status": "NO_GO",
        "public_beta_status": "NO_GO",
    }
    inventory.write_text(json.dumps(inventory_payload), encoding="utf-8")
    return archive, archive_sha, inventory, _sha256(inventory)


def _write_fake_managed_rootfs_inventory(programdata: Path) -> tuple[Path, str, Path, str]:
    rootfs = programdata / "runtime" / "rootfs" / "ImmoAppRuntime.rootfs.tar"
    inventory = programdata / "config" / "managed_wsl2_runtime_rootfs_inventory.json"
    _write_immoapp_rootfs_tar(rootfs)
    rootfs_sha = _sha256(rootfs)
    payload = {
        "kind": "immoapp_managed_wsl2_runtime_rootfs_inventory",
        "schema_version": 1,
        "created_at_utc": "2026-01-01T00:00:00Z",
        "source_commit_sha": "a" * 40,
        "base_rootfs_tar_path": str(rootfs),
        "base_rootfs_tar_sha256": rootfs_sha,
        "output_rootfs_tar_path": str(rootfs),
        "output_rootfs_tar_sha256": rootfs_sha,
        "runtime_version": "0.1.0",
        "expected_distro_name": "ImmoAppRuntime",
        "required_entries": list(MANAGED_WSL2_ROOTFS_REQUIRED_ENTRIES),
        "rootfs_artifact_status": "GO",
        "runtime_identity_status": "NO-GO",
        "runtime_start_status": "NO-GO",
        "agency_install_status": "NO_GO",
        "public_beta_status": "NO_GO",
        "proof_result": "GO",
        "reason_code": "managed_wsl2_runtime_rootfs_built",
    }
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    return rootfs, rootfs_sha, inventory, _sha256(inventory)


def _write_fake_packaged_managed_wsl2_payload(
    tmp_path: Path, programdata: Path, env: dict[str, str]
) -> dict[str, str]:
    package_root = tmp_path / "packaged-managed-runtime"
    _write_fake_managed_rootfs_inventory(programdata)
    _write_fake_managed_image_bundle(programdata)
    artifact_inventory = programdata / "config" / "managed_wsl2_runtime_artifact_inventory.json"
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_artifact.ps1"),
            "-OutputJson",
            str(artifact_inventory),
            "-AllowTestOnlyPath",
        ],
        env=env,
    )
    copies = (
        (
            programdata / "runtime" / "rootfs" / "ImmoAppRuntime.rootfs.tar",
            package_root / "rootfs" / "ImmoAppRuntime.rootfs.tar",
        ),
        (
            programdata / "config" / "managed_wsl2_runtime_rootfs_inventory.json",
            package_root / "config" / "managed_wsl2_runtime_rootfs_inventory.json",
        ),
        (
            programdata / "runtime" / "images" / "immoapp-runtime-images.tar",
            package_root / "images" / "immoapp-runtime-images.tar",
        ),
        (
            programdata / "config" / "managed_wsl2_runtime_image_bundle_inventory.json",
            package_root / "config" / "managed_wsl2_runtime_image_bundle_inventory.json",
        ),
        (
            artifact_inventory,
            package_root / "config" / "managed_wsl2_runtime_artifact_inventory.json",
        ),
    )
    for source, destination in copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copytree(
        programdata / "runtime" / "managed-wsl2-artifact",
        package_root / "artifact" / "managed-wsl2-artifact",
        dirs_exist_ok=True,
    )
    updated = dict(env)
    updated["IMMOAPP_TEST_PACKAGED_MANAGED_RUNTIME_ROOT"] = str(package_root)
    updated["IMMOAPP_ALLOW_TEST_OWNER_AUTHORIZATION_CONFIRMATION"] = "1"
    return updated


def _run_image_bundle_inventory_validator(
    programdata: Path,
    inventory: Path,
    *,
    expected_inventory_sha: str = "",
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    command = (
        f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
        f"$inventoryPath = {_ps_quote(inventory)}; "
        "$payload = Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json; "
        "try { "
        "$result = Assert-ImmoAppManagedWsl2ImageBundleInventoryReady "
        "-Inventory $payload "
        f"-ExpectedInventorySha256 {_ps_quote(expected_inventory_sha)} "
        "-ImageBundleInventoryPath $inventoryPath "
        "-AllowTestOnlyPath; "
        "[ordered]@{ ok = $true; result = $result } | ConvertTo-Json -Depth 12 "
        "} catch { "
        "[ordered]@{ ok = $false; error = [string]$_.Exception.Message } "
        "| ConvertTo-Json -Depth 12; exit 1 "
        "}"
    )
    return _run_powershell(["-Command", command], env=env, check=check)


def _write_fake_image_bundle_docker(
    bin_dir: Path,
    *,
    app_revision_label: str | None,
    build_progress_on_stderr: bool = False,
) -> tuple[Path, Path]:
    bin_dir.mkdir(parents=True, exist_ok=True)
    docker = bin_dir / "docker.cmd"
    log = bin_dir / "docker-args.log"
    app_label_json = (
        f'{{"org.opencontainers.image.revision":"{app_revision_label}"}}'
        if app_revision_label is not None
        else "{}"
    )
    docker.write_text(
        "\r\n".join(
            [
                "@echo off",
                f'echo %*>>"{log}"',
                'if "%1"=="build" (',
                (
                    "  echo #0 fake BuildKit progress 1>&2"
                    if build_progress_on_stderr
                    else "  rem no build progress"
                ),
                "  exit /b 0",
                ")",
                'if "%1"=="image" if "%2"=="inspect" if "%4"=="--format" (',
                f'  if "%3"=="immoapp-server:local" echo {app_label_json}& exit /b 0',
                '  echo ^"%3@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa^"',
                "  exit /b 0",
                ")",
                'if "%1"=="image" if "%2"=="inspect" exit /b 0',
                'if "%1"=="image" if "%2"=="tag" exit /b 0',
                'if "%1"=="save" if "%2"=="-o" (echo fake archive>"%3" & exit /b 0)',
                "echo unsupported fake docker args: %* 1>&2",
                "exit /b 42",
            ]
        )
        + "\r\n",
        encoding="ascii",
    )
    return docker, log


def _run_image_bundle_builder_with_fake_docker(
    tmp_path: Path,
    *,
    app_revision_label: str | None,
    source_commit_sha: str,
    build_app_image: bool = False,
    build_progress_on_stderr: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any], Path]:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    docker, log = _write_fake_image_bundle_docker(
        tmp_path / "bin",
        app_revision_label=app_revision_label,
        build_progress_on_stderr=build_progress_on_stderr,
    )
    archive = programdata / "runtime" / "images" / "immoapp-runtime-images.tar"
    inventory = programdata / "config" / "managed_wsl2_runtime_image_bundle_inventory.json"
    args = [
        "-File",
        str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_image_bundle.ps1"),
        "-DockerExe",
        str(docker),
        "-SourceCommitSha",
        source_commit_sha,
        "-OutputArchivePath",
        str(archive),
        "-OutputJson",
        str(inventory),
        "-AllowTestOnlyPath",
    ]
    if build_app_image:
        args.append("-BuildAppImage")
    result = _run_powershell(
        args,
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    payload = json.loads(inventory.read_text(encoding="utf-8-sig"))
    return result, payload, log


def _git_sh_path(path: Path) -> str:
    resolved = path.resolve()
    posix = resolved.as_posix()
    drive = resolved.drive.rstrip(":").lower()
    return f"/{drive}{posix[2:]}"


def _run_managed_runtime_shell_script(
    tmp_path: Path,
    script_name: str,
    *,
    fail_compose_action: str,
) -> subprocess.CompletedProcess[str]:
    sh = Path("C:/Program Files/Git/usr/bin/sh.exe")
    runtime_root = tmp_path / "runtime"
    runtime_bin = runtime_root / "bin"
    compose_dir = runtime_root / "compose"
    fake_bin = tmp_path / "fake-bin"
    runtime_bin.mkdir(parents=True)
    compose_dir.mkdir(parents=True)
    fake_bin.mkdir(parents=True)
    (compose_dir / "compose.yaml").write_text(
        "services:\n  web:\n    image: test\n", encoding="utf-8"
    )
    (runtime_bin / "managed-hub-common").write_text(
        _read("deployment/managed-runtime/bin/managed-hub-common"),
        encoding="utf-8",
    )
    script_text = _read(f"deployment/managed-runtime/bin/{script_name}").replace(
        ". /opt/immoapp/runtime/bin/managed-hub-common",
        '. "$IMMOAPP_RUNTIME_ROOT/bin/managed-hub-common"',
    )
    script = runtime_bin / script_name
    script.write_text(script_text, encoding="utf-8")
    docker = fake_bin / "docker"
    docker.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "info" ]; then echo "Server Version: fake"; exit 0; fi',
                (
                    'if [ "$1" = "compose" ] && [ "$2" = "version" ]; '
                    'then echo "Docker Compose version fake"; exit 0; fi'
                ),
                'if [ "$1" = "compose" ]; then',
                '  for arg in "$@"; do',
                (
                    f'    if [ "$arg" = "{fail_compose_action}" ]; '
                    f'then echo "{fail_compose_action} failed"; exit 42; fi'
                ),
                "  done",
                "fi",
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_git_sh_path(fake_bin)}:/usr/bin:/bin",
            "IMMOAPP_RUNTIME_ROOT": _git_sh_path(runtime_root),
            "IMMOAPP_RUNTIME_COMMAND_TIMEOUT_SECONDS": "2",
            "IMMOAPP_COMPOSE_UP_TIMEOUT_SECONDS": "2",
        }
    )
    return subprocess.run(
        [str(sh), _git_sh_path(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _write_tar(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w") as bundle:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name in MANAGED_WSL2_ROOTFS_REQUIRED_ENTRIES else 0o644
            bundle.addfile(info, io.BytesIO(data))


def _write_immoapp_rootfs_tar(path: Path) -> None:
    entries = {name: b"#!/bin/sh\nexit 0\n" for name in MANAGED_WSL2_ROOTFS_REQUIRED_ENTRIES}
    entries["etc/os-release"] = b"ID=immoapp-test\n"
    _write_tar(path, entries)


def _write_backup_restore_evidence(
    tmp_path: Path, overrides: dict[str, object] | None = None
) -> Path:
    backup_bundle = tmp_path / "backup.bundle"
    backup_bundle.write_bytes(b"backup")
    payload: dict[str, object] = {
        "kind": "immoapp_beta_release_backup_restore_evidence",
        "schema_version": 1,
        "proof_result": "GO",
        "restore_database": "immoapp_restore",
        "isolated_restore_bucket": "immoapp-restore-drill-20260101000000-aaaaaaaa",
        "storage_objects_checked": 1,
        "storage_objects_hash_verified": 1,
        "live_source_bucket_used_as_restore_target": False,
        "backup_bundle_path": str(backup_bundle),
        "backup_bundle_sha256": _sha256(backup_bundle),
    }
    if overrides:
        payload.update(overrides)
    path = tmp_path / "backup_restore.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _strict_backup_check(path: Path, **expected: str) -> dict[str, Any]:
    args = [
        ".",
        str(REPO_ROOT / "scripts" / "common.ps1"),
        ";",
        "$result",
        "=",
        "Test-ImmoAppStrictBackupRestoreEvidence",
        "-Path",
        _ps_quote(path),
    ]
    for key, value in expected.items():
        args.extend([f"-{key}", _ps_quote(value)])
    command = " ".join(args) + "; $result | ConvertTo-Json -Depth 6"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return cast(dict[str, Any], json.loads(result.stdout))


def _ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_runtime_log_retention(
    programdata: Path,
    *,
    logs_root: Path | None = None,
    output: Path | None = None,
    retention_days: int = 14,
    max_total_bytes: int = 536870912,
    check: bool = True,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    logs_root = logs_root or (programdata / "logs" / "managed-runtime")
    output = output or (programdata / "logs" / "managed_runtime_log_retention.json")
    command = (
        f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
        "$payload = Invoke-ImmoAppManagedRuntimeLogRetention "
        f"-LogsRoot {_ps_quote(logs_root)} "
        f"-OutputJson {_ps_quote(output)} "
        f"-RetentionDays {retention_days} "
        f"-MaxTotalBytes {max_total_bytes}; "
        "$payload | ConvertTo-Json -Depth 12; "
        "if ($payload.proof_result -ne 'GO') { exit 1 }"
    )
    result = _run_powershell(
        ["-Command", command],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=check,
    )
    return result, cast(dict[str, Any], json.loads(result.stdout))


def _run_official_rootfs_builder(
    programdata: Path,
    *extra_args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    output = programdata / "config" / "managed_wsl2_official_rootfs_build.json"
    command = [
        "-File",
        str(REPO_ROOT / "scripts" / "build_official_managed_wsl2_runtime_rootfs.ps1"),
        "-OutputJson",
        str(output),
        *extra_args,
    ]
    full_env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    if env:
        full_env.update(env)
    result = _run_powershell(command, env=full_env, check=check)
    return result, cast(dict[str, Any], json.loads(result.stdout))


def _set_mtime_days_ago(path: Path, days: int) -> None:
    stamp = time.time() - (days * 24 * 60 * 60)
    os.utime(path, (stamp, stamp))


def _open_exclusive_windows_file_handle(path: Path) -> int:
    if os.name != "nt":
        pytest.skip("exclusive Windows file handle proof only applies on Windows")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    generic_read = 0x80000000
    share_none = 0
    open_existing = 3
    file_attribute_normal = 0x80
    handle = kernel32.CreateFileW(
        str(path),
        generic_read,
        share_none,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), f"CreateFileW failed for {path}")
    return int(handle)


def _close_windows_file_handle(handle: int) -> None:
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(wintypes.HANDLE(handle))


def _detect_provider(
    provider: Path, env: dict[str, str] | None = None, *, use_provider_arg: bool = True
) -> dict[str, Any]:
    args = ["-File", str(REPO_ROOT / "scripts" / "detect_hub_runtime.ps1")]
    if use_provider_arg:
        args.extend(["-ProviderConfigPath", str(provider)])
    result = _run_powershell(args, env=env)
    return cast(dict[str, Any], json.loads(result.stdout))


def _build_managed_runtime_package(
    source: Path,
    output: Path,
    *extra_args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    if env is None:
        env = {
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(output.parent),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        }
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_hub_runtime_package.ps1"),
            "-RuntimeSourceRoot",
            str(source),
            "-OutputRoot",
            str(output),
            *extra_args,
        ],
        env=env,
        check=check,
    )
    inventory_path = output / "managed_hub_runtime_package_inventory.json"
    data = cast(dict[str, Any], json.loads(inventory_path.read_text(encoding="utf-8-sig")))
    return result, data


def test_hub_setup_wrapper_exposes_m1_roles_without_final_installer_claims() -> None:
    setup = _read("scripts/setup_office_hub.ps1")
    common = _read("scripts/common.ps1")
    assert 'ValidateSet("HubDesktop", "WorkstationOnly", "HubOnly")' in setup
    assert "HubOnly is a future packaging role" not in setup
    assert '$Role -eq "HubOnly"' in setup
    assert '"hub_only"' in setup
    assert "Set-ImmoAppHubLanRuntimeEnv" in setup
    assert "HubDisplayName" in setup
    assert "Write-ImmoAppHubIdentity" in setup
    assert "HubDesktop setup requires -HubDisplayName" in setup
    assert 'Invoke-ImmoAppHubRuntimeProfile -Action "generate"' in setup
    assert "WorkstationOnly setup requires a Hub front-door URL, not localhost" in setup
    assert "verify_lan_workstation_reachability.ps1" in setup
    assert "set_client_api_endpoint.ps1" in setup
    assert "New-HubManagerShortcut" in setup
    assert "Resolve-HubManagerAppPath" in setup
    assert "ImmoApp Hub Manager.exe" in setup
    assert (
        '$shortcut.Arguments = if ([string]::IsNullOrWhiteSpace($Action)) { "" } else { "--action $Action" }'
        in setup
    )
    assert (
        '$shortcuts += New-HubManagerShortcut -Name "ImmoApp Hub Manager" '
        "-ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath"
    ) in setup
    assert (
        '$shortcuts += New-HubManagerShortcut -Name "ImmoApp Hub Manager" '
        '-ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "status"'
    ) not in setup
    for shortcut in (
        "ImmoApp Hub Manager",
        "Restart ImmoApp Hub",
        "Rename ImmoApp Hub",
        "ImmoApp Hub Connection Details",
        "ImmoApp Hub Runtime Status",
        "ImmoApp Hub Firewall Status",
        "Copy ImmoApp Hub Connection URL",
        "Backup ImmoApp Hub Now",
        "Open ImmoApp Desktop",
    ):
        assert shortcut in setup
    assert "detect_hub_runtime.ps1" in setup
    assert "runtime_detection = $runtimeDetection" in setup
    assert "$runtimeMode = [string]$runtimeDetection.runtime_dependency_mode" in setup
    assert "agency_install_status = [string]$runtimeDetection.agency_install_status" in setup
    assert "runtime_provider_proof" in setup
    assert "[string]$SetupRunId" in setup
    assert "setup_run_id = $SetupRunId" in setup
    assert "selected_install_desktop" in setup
    assert "selected_install_hub" in setup
    assert "install_mode" in setup
    assert "elevated_setup_required" in setup
    assert "elevated_setup_observed" in setup
    assert "hub_setup_requires_elevation" in setup
    assert "Resolve-ImmoAppHubManagerScript" in setup
    assert "Resolve-ImmoAppDesktopExecutable" in setup
    assert "Test-ImmoAppInstalledSource" in setup
    assert "hub_manager_script_source" in setup
    assert "hub_manager_app_path" in setup
    assert "hub_manager_app_present" in setup
    assert "desktop_exe_source" in setup
    assert "repo_dev" in setup
    assert "installed_app" in common
    assert "installed_programdata" in common
    assert "[switch]$NoStartHub" in setup
    assert "$shouldStartHub = (-not $ValidateOnly) -and (-not $NoStartHub.IsPresent)" in setup
    assert "starts_backend_services = [bool]$shouldStartHub" in setup
    assert setup.count("Initialize-ImmoAppEnvFileFromTemplate") == 1
    workstation_block = setup.split('if ($Role -eq "WorkstationOnly") {', 1)[1].split("else {", 1)[
        0
    ]
    assert "stack.ps1" not in workstation_block
    assert "Invoke-ImmoAppHubRuntimeProfile" not in workstation_block
    assert "Invoke-HubRuntimeDetection" not in workstation_block
    assert "Ensure-ImmoAppHubFirewallRule" not in workstation_block
    assert "Get-ImmoAppHubFirewallRuleEvidence" in common
    assert "Ensure-ImmoAppHubFirewallRule" in common
    assert "already_present_valid" in common
    assert "already_present_invalid" in common
    firewall_block = common.split("function Ensure-ImmoAppHubFirewallRule", 1)[1].split(
        "function Test-ImmoAppCurrentProcessElevated", 1
    )[0]
    assert (
        '$wasInvalid = ([string]$existing.status -eq "already_present_invalid")' in firewall_block
    )
    assert "Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction Stop" in firewall_block
    assert '"firewall_rule_updated_and_verified"' in firewall_block
    assert '"firewall_rule_update_failed"' in firewall_block
    assert '@("created", "updated", "already_present_valid")' in setup
    assert "skipped_local_only" in common
    assert "skipped_no_lan_requested" in common


def test_installed_hub_runtime_profile_does_not_write_bytecode_into_payload() -> None:
    common = _read("scripts/common.ps1")
    profile_block = common.split("function Invoke-ImmoAppHubRuntimeProfile", 1)[1].split(
        "function Set-ImmoAppHubRuntimeProfileEnv", 1
    )[0]
    assert "& $python -B $script $Action --format $Format" in profile_block


def test_hub_manager_is_thin_wrapper_over_existing_runtime_tools() -> None:
    manager = _read("scripts/hub_manager.ps1")
    app = _read("app/hub_manager_app.py")
    actions = _read("app/hub_manager_actions.py")
    assert (
        'ValidateSet("start", "stop", "restart", "status", "health", "logs", "support", "backup-now", "open-desktop", "copy-url", "rename-hub", "finish-hub-setup", "identity", "front-door", "runtime-status", "install-runtime-candidate", "install-runtime-artifact", "remove-runtime-candidate", "cleanup-runtime-logs", "delete-hub-data", "firewall-status", "connection-details")'
        in manager
    )
    assert "stack.ps1" in manager
    assert "Get-ImmoAppCurrentScriptRootSource" in manager
    assert "managed_runtime_provider_missing" in manager
    assert "Installed Hub Manager requires an ImmoApp-managed runtime provider" in manager
    assert "collect_hub_status_evidence.ps1" in manager
    assert "Add-HubManagerLocalStateToPayload" in manager
    assert "hub_state_manifest_status = [string]$state.hub_state_manifest_status" in manager
    assert "collect_desktop_support_bundle.ps1" in manager
    assert 'Invoke-ManagedWsl2RuntimeArtifactAction -ManagedAction "backup"' in manager
    assert "Managed WSL2 runtime backup" in manager
    assert (
        "Installed Hub Manager requires an ImmoApp-managed runtime provider for backup" in manager
    )
    managed_action_block = manager.split("function Invoke-ManagedWsl2RuntimeArtifactAction", 1)[
        1
    ].split("function Resolve-DesktopExePath", 1)[0]
    assert "$effectiveHubBaseUrl = $HubBaseUrl" in manager
    assert "$effectiveHubBaseUrl = Get-ImmoAppHubBaseUrl -PreferLan" not in managed_action_block
    assert "LAN reachability is collected separately" in managed_action_block
    assert '@("-HubBaseUrl", $effectiveHubBaseUrl)' in manager
    assert "Resolve-ImmoAppDesktopExecutable" in manager
    assert "Set-Clipboard" in manager
    assert "set_hub_identity.ps1" in manager
    assert 'Read-Host "Hub name"' in manager
    assert "Get-HubDisplayNameForManager" in manager
    assert "immoapp_hub_manager_identity" in manager
    assert "immoapp_hub_manager_front_door" in manager
    assert "immoapp_hub_manager_firewall_status" in manager
    assert "immoapp_hub_manager_connection_details" in manager
    assert "immoapp_hub_manager_managed_wsl2_runtime_candidate_install" in manager
    assert "immoapp_hub_manager_managed_wsl2_runtime_candidate_remove" in manager
    assert "immoapp_hub_manager_managed_wsl2_runtime_artifact_install" in manager
    assert "collect_managed_wsl2_runtime_start_evidence.ps1" in manager
    assert "ConfirmInstallRuntimeCandidate" in manager
    assert "ConfirmInstallRuntimeArtifact" in manager
    assert "ConfirmDeleteHubData" in manager
    assert "OwnerAuthorizationEvidenceJson" in manager
    assert "Read-ImmoAppHubOwnerAuthorizationEvidence" in manager
    assert "immoapp_hub_manager_owner_authorization" in manager
    assert "TypedConfirmation" in manager
    assert "DELETE HUB DATA" in app
    assert "HubManagerLoginDialog" in app
    assert "authorization_action=action" in app
    assert "owner_authorization_evidence_path" in app
    assert "_owner_password" not in app
    assert "from app.widgets.register_dialog import RegisterDialog" in app
    assert "from app.widgets.activate_dialog import ActivateDialog" in app
    assert "open_owner_registration" in app
    assert "open_owner_activation" in app
    assert "requires_owner_authorization" in actions
    assert "hub_manager_protected_action" in _read(
        "scripts/create_hub_owner_authorization_evidence.py"
    )
    assert "candidate_registration_status" in manager
    assert "runtime_artifact_status" in manager
    assert "registration_only" in manager
    assert "managed_wsl2_runtime_artifact_missing" in manager
    assert "managed_wsl2_runtime_start_not_proven" in manager
    assert "Install-HubManagerPackagedManagedWsl2Payload" in manager
    assert "packaged_payload_status" in manager
    assert "packaged_managed_runtime_payload_missing" in manager
    assert "build_managed_wsl2_runtime_artifact.ps1" not in manager
    assert "Finish ImmoApp Office Hub Setup" in manager
    assert "New-HubManagerSetupRunId" in manager
    assert "Resolve-HubManagerPowerShellPath" in manager
    assert "System32\\WindowsPowerShell\\v1.0\\powershell.exe" in manager
    assert "Quote-WindowsCommandLineArgument" in manager
    assert "Join-WindowsCommandLineArguments" in manager
    assert "-SetupRunId" in manager
    assert "-NoAutoStart" in manager
    assert "-NoStartHub" in manager
    finish_block = manager.split('"finish-hub-setup" {', 1)[1]
    assert "Start-Process" in finish_block
    assert "-FilePath $powerShellPath" in finish_block
    assert "-ArgumentList $arguments" in finish_block
    assert "-Verb RunAs" in finish_block
    assert "Remove-Item -LiteralPath $evidencePath -Force" in finish_block
    assert "selected_install_hub" in finish_block
    assert "install_mode" in finish_block
    assert "-Action start" not in finish_block
    assert "tiny:" not in manager.lower()
    assert "small:" not in manager.lower()
    assert "medium:" not in manager.lower()
    assert "large:" not in manager.lower()
    assert 'HUB_MANAGER_SCRIPT_NAME = "hub_manager.ps1"' in actions
    assert "build_hub_manager_command" in actions
    assert "-OutputJson" in actions
    assert (
        "Invoke-ManagedWsl2RuntimeArtifactAction -ManagedAction $managedAction -Path $Path"
        in manager
    )
    for stack_action in ("up", "down", "restart-app"):
        assert f'Invoke-StackAction -StackAction "{stack_action}" -Path $OutputJson' in manager
    assert 'Invoke-StackAction -StackAction "logs" -Path $OutputJson' in manager
    assert "ConfirmInstallRuntimeArtifact" in actions
    assert "ConfirmInstallRuntimeCandidate" not in actions
    assert "stack.ps1" not in app
    assert "stack.ps1" not in actions


def test_managed_wsl2_runtime_policy_scripts_exist_and_are_plan_only() -> None:
    policy = _read("scripts/managed_wsl2_runtime_policy.ps1")
    configure = _read("scripts/configure_managed_wsl2_runtime.ps1")
    assert "immoapp_managed_wsl2_runtime_policy" in policy
    assert "MachineTotalMemoryGb" in policy
    assert "MachineLogicalProcessors" in policy
    assert "available_ram" not in policy.lower()
    assert "free_ram" not in policy.lower()
    assert "cap_is_ceiling_not_reservation" in policy
    assert "global_wsl_config_scope" in policy
    assert "autoMemoryReclaim" in configure
    assert "ConfirmGlobalWslConfigChange" in configure
    assert "ApplyShutdown" in configure
    assert "wsl --shutdown" in configure


def test_managed_wsl2_policy_rejects_below_8gb_and_never_agency_go() -> None:
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
            "-PlanOnly",
            "-MachineTotalMemoryGb",
            "7.4",
            "-MachineLogicalProcessors",
            "4",
        ]
    )
    payload = json.loads(result.stdout)
    assert payload["policy_result"] == "NO-GO"
    assert payload["reason_code"] == "machine_below_minimum_hub_ram"
    assert payload["agency_install_status"] == "NO_GO"


def test_managed_wsl2_policy_8gb_is_tiny_with_minimum_warning() -> None:
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
            "-PlanOnly",
            "-MachineTotalMemoryGb",
            "8",
            "-MachineLogicalProcessors",
            "4",
        ]
    )
    payload = json.loads(result.stdout)
    assert payload["policy_result"] == "GO"
    assert payload["selected_hub_machine_tier"] == "tiny"
    assert payload["selected_hub_runtime_profile"] == "tiny"
    assert "hub_on_minimum_ram" in payload["warning_codes"]
    assert payload["planned_wsl_memory_gb"] <= 3
    assert payload["cap_is_ceiling_not_reservation"] is True
    assert payload["startup_spike_not_failure"] is True
    assert payload["sustained_pressure_backoff_required"] is True
    assert payload["planned_auto_memory_reclaim"] != "disabled"


def test_managed_wsl2_policy_16gb_and_32gb_caps_are_bounded() -> None:
    small = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "4",
            ]
        ).stdout
    )
    large = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "32",
                "-MachineLogicalProcessors",
                "8",
            ]
        ).stdout
    )
    assert small["policy_result"] == "GO"
    assert 4 <= small["planned_wsl_memory_gb"] <= 5
    assert small["planned_wsl_processors"] <= 3
    assert large["policy_result"] == "GO"
    assert large["planned_wsl_memory_gb"] > small["planned_wsl_memory_gb"]
    assert large["planned_wsl_processors"] > small["planned_wsl_processors"]


@pytest.mark.parametrize(
    ("ram_gb", "cpu_count", "expected_profile"),
    [
        ("32", "2", "tiny"),
        ("32", "4", "small"),
        ("32", "8", "large"),
        ("16", "12", "medium"),
        ("16", "4", "small"),
    ],
)
def test_managed_wsl2_policy_uses_weakest_memory_and_cpu_dimension(
    ram_gb: str, cpu_count: str, expected_profile: str
) -> None:
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                ram_gb,
                "-MachineLogicalProcessors",
                cpu_count,
            ]
        ).stdout
    )
    assert payload["policy_result"] == "GO"
    assert payload["selected_hub_machine_tier"] == expected_profile
    assert payload["selected_hub_runtime_profile"] == expected_profile
    assert (
        payload["planned_wsl_memory_gb"]
        <= {
            "tiny": 3,
            "small": 5,
            "medium": 8,
            "large": 12,
        }[expected_profile]
    )
    assert (
        payload["planned_wsl_processors"]
        <= {
            "tiny": 2,
            "small": 4,
            "medium": 6,
            "large": 8,
        }[expected_profile]
    )


def test_managed_wsl2_policy_uses_runtime_profile_envelope_when_supplied(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "hub_runtime_profile.json"
    profile.write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_runtime_profile",
                "schema_version": 1,
                "selected_profile": "tiny",
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "12",
                "-RuntimeProfileJson",
                str(profile),
            ]
        ).stdout
    )
    assert payload["policy_result"] == "GO"
    assert payload["selected_hub_machine_tier"] == "medium"
    assert payload["observed_hub_runtime_profile"] == "tiny"
    assert payload["selected_hub_runtime_profile"] == "tiny"
    assert payload["runtime_profile_source"] == "explicit_runtime_profile_json"
    assert payload["runtime_profile_status"] == "valid"
    assert Path(payload["runtime_profile_path"]) == profile
    assert payload["runtime_profile_sha256"] == hashlib.sha256(profile.read_bytes()).hexdigest()
    assert payload["runtime_profile_error"] == ""
    assert payload["planned_wsl_memory_gb"] == 3
    assert payload["planned_wsl_processors"] == 2


def test_managed_wsl2_policy_records_machine_capacity_without_runtime_profile(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "12",
            ],
            env={
                "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
                "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            },
        ).stdout
    )
    assert payload["policy_result"] == "GO"
    assert payload["selected_hub_machine_tier"] == "medium"
    assert payload["selected_hub_runtime_profile"] == "medium"
    assert payload["runtime_profile_source"] == "machine_capacity"
    assert payload["runtime_profile_status"] == "missing"
    assert payload["runtime_profile_path"] == ""
    assert payload["runtime_profile_sha256"] == ""
    assert payload["runtime_profile_error"] == ""
    assert payload["observed_hub_runtime_profile"] == ""
    assert payload["planned_wsl_memory_gb"] >= 8
    assert payload["planned_wsl_processors"] == 6


def test_managed_wsl2_policy_uses_default_persisted_runtime_profile_with_provenance(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    config = programdata / "config"
    config.mkdir(parents=True)
    profile = config / "hub_runtime_profile.json"
    profile.write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_runtime_profile",
                "schema_version": 1,
                "selected_profile": "medium",
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "32",
                "-MachineLogicalProcessors",
                "8",
            ],
            env={
                "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
                "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            },
        ).stdout
    )
    assert payload["policy_result"] == "GO"
    assert payload["selected_hub_machine_tier"] == "large"
    assert payload["selected_hub_runtime_profile"] == "medium"
    assert payload["runtime_profile_source"] == "default_persisted_config"
    assert payload["runtime_profile_status"] == "valid"
    assert Path(payload["runtime_profile_path"]) == profile
    assert payload["runtime_profile_sha256"] == hashlib.sha256(profile.read_bytes()).hexdigest()
    assert payload["runtime_profile_error"] == ""
    assert payload["observed_hub_runtime_profile"] == "medium"


def test_managed_wsl2_policy_explicit_missing_runtime_profile_is_no_go(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-profile.json"
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "12",
                "-RuntimeProfileJson",
                str(missing),
            ]
        ).stdout
    )
    assert payload["policy_result"] == "NO-GO"
    assert payload["reason_code"] == "explicit_runtime_profile_missing"
    assert payload["runtime_profile_source"] == "explicit_runtime_profile_json"
    assert payload["runtime_profile_status"] == "missing"
    assert Path(payload["runtime_profile_path"]) == missing


def test_managed_wsl2_policy_invalid_runtime_profile_is_no_go(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "invalid-profile.json"
    profile.write_text(
        json.dumps({"kind": "immoapp_hub_runtime_profile", "selected_profile": "huge"}),
        encoding="utf-8",
    )
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "12",
                "-RuntimeProfileJson",
                str(profile),
            ]
        ).stdout
    )
    assert payload["policy_result"] == "NO-GO"
    assert payload["reason_code"] == "runtime_profile_invalid_selected_profile"
    assert payload["runtime_profile_status"] == "invalid_selected_profile"
    assert payload["runtime_profile_sha256"] == hashlib.sha256(profile.read_bytes()).hexdigest()


def test_managed_wsl2_policy_default_invalid_runtime_profile_is_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    config = programdata / "config"
    config.mkdir(parents=True)
    profile = config / "hub_runtime_profile.json"
    profile.write_text(json.dumps({"selected_profile": "huge"}), encoding="utf-8")
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "12",
            ],
            env={
                "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
                "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            },
        ).stdout
    )
    assert payload["policy_result"] == "NO-GO"
    assert payload["reason_code"] == "runtime_profile_invalid_selected_profile"
    assert payload["runtime_profile_source"] == "default_persisted_config"
    assert payload["runtime_profile_status"] == "invalid_selected_profile"


def test_managed_wsl2_policy_invalid_runtime_profile_json_is_no_go(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "corrupt-profile.json"
    profile.write_text("{not-json", encoding="utf-8")
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "12",
                "-RuntimeProfileJson",
                str(profile),
            ]
        ).stdout
    )
    assert payload["policy_result"] == "NO-GO"
    assert payload["reason_code"] == "runtime_profile_invalid_json"
    assert payload["runtime_profile_status"] == "invalid_json"
    assert payload["runtime_profile_sha256"] == hashlib.sha256(profile.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("ram_gb", "expected_result", "expected_tier", "min_memory"),
    [
        ("7.4", "NO-GO", "workstation_only", 0),
        ("7.5", "GO", "tiny", 3),
        ("8", "GO", "tiny", 3),
        ("15.7", "GO", "medium", 4),
        ("16", "GO", "medium", 4),
        ("31.5", "GO", "large", 8),
        ("32", "GO", "large", 8),
    ],
)
def test_managed_wsl2_policy_normalizes_common_installed_ram_classes(
    ram_gb: str, expected_result: str, expected_tier: str, min_memory: int
) -> None:
    payload = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
                "-PlanOnly",
                "-MachineTotalMemoryGb",
                ram_gb,
                "-MachineLogicalProcessors",
                "12",
            ]
        ).stdout
    )
    assert payload["policy_result"] == expected_result
    assert payload["selected_hub_machine_tier"] == expected_tier
    assert payload["planned_wsl_memory_gb"] >= min_memory
    if expected_result == "GO":
        assert payload["agency_install_status"] == "NO_GO"


def test_configure_managed_wsl2_runtime_requires_confirmation_and_preserves_conflicts(
    tmp_path: Path,
) -> None:
    existing = tmp_path / ".wslconfig"
    original = "[wsl2]\nmemory=6GB\nprocessors=4\n"
    existing.write_text(original, encoding="utf-8")
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "configure_managed_wsl2_runtime.ps1"),
            "-PlanOnly",
            "-ExistingWslConfigPath",
            str(existing),
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "4",
        ]
    )
    payload = json.loads(result.stdout)
    assert payload["apply_performed"] is False
    assert payload["reason_code"] == "existing_wslconfig_conflict_requires_allow_merge"
    assert payload["existing_wslconfig_preserved"] is True
    assert existing.read_text(encoding="utf-8") == original

    confirmed_without_merge = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "configure_managed_wsl2_runtime.ps1"),
                "-Apply",
                "-ConfirmGlobalWslConfigChange",
                "-ExistingWslConfigPath",
                str(existing),
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "4",
            ]
        ).stdout
    )
    assert confirmed_without_merge["apply_performed"] is False
    assert (
        confirmed_without_merge["reason_code"] == "existing_wslconfig_conflict_requires_allow_merge"
    )
    assert existing.read_text(encoding="utf-8") == original

    apply_without_confirm = json.loads(
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "configure_managed_wsl2_runtime.ps1"),
                "-Apply",
                "-ExistingWslConfigPath",
                str(existing),
                "-MachineTotalMemoryGb",
                "16",
                "-MachineLogicalProcessors",
                "4",
            ]
        ).stdout
    )
    assert apply_without_confirm["apply_performed"] is False
    assert apply_without_confirm["reason_code"] == "confirm_global_wsl_config_change_required"


def _run_confirmed_wsl_apply(
    user_profile: Path, *, extra_args: list[str] | None = None
) -> dict[str, Any]:
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "configure_managed_wsl2_runtime.ps1"),
            "-Apply",
            "-ConfirmGlobalWslConfigChange",
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "4",
            *(extra_args or []),
        ],
        env={"USERPROFILE": str(user_profile)},
    )
    return cast(dict[str, Any], json.loads(result.stdout))


def test_configure_managed_wsl2_runtime_confirmed_apply_creates_wslconfig(
    tmp_path: Path,
) -> None:
    user_profile = tmp_path / "profile"
    user_profile.mkdir()
    payload = _run_confirmed_wsl_apply(user_profile)
    wslconfig = user_profile / ".wslconfig"
    assert payload["apply_performed"] is True
    assert payload["final_wslconfig_verified"] is True
    assert payload["final_wslconfig_missing_keys"] == []
    assert payload["temp_wslconfig_removed"] is True
    assert payload["existing_wslconfig_backup_verified"] is False
    assert payload["wsl_shutdown_required"] is True
    assert payload["wsl_shutdown_performed"] is False
    assert wslconfig.exists()
    text = wslconfig.read_text(encoding="utf-8")
    assert "[wsl2]" in text
    assert "memory=5GB" in text
    assert "processors=3" in text
    assert "swap=2GB" in text
    assert "autoMemoryReclaim=gradual" in text


def test_configure_managed_wsl2_runtime_updates_wsl2_settings_in_place(
    tmp_path: Path,
) -> None:
    user_profile = tmp_path / "profile"
    user_profile.mkdir()
    wslconfig = user_profile / ".wslconfig"
    wslconfig.write_text("# keep\n[wsl2]\nmemory=9GB\nprocessors=9\n", encoding="utf-8")
    payload = _run_confirmed_wsl_apply(user_profile, extra_args=["-AllowMergeExistingWslConfig"])
    text = wslconfig.read_text(encoding="utf-8")
    assert payload["apply_performed"] is True
    assert payload["final_wslconfig_verified"] is True
    assert payload["temp_wslconfig_removed"] is True
    assert payload["existing_wslconfig_backup_verified"] is True
    assert payload["existing_wslconfig_backup_path"]
    assert Path(payload["existing_wslconfig_backup_path"]).exists()
    assert "# keep" in text
    assert "memory=5GB" in text
    assert "processors=3" in text
    assert "swap=2GB" in text
    assert "autoMemoryReclaim=gradual" in text
    assert "memory=9GB" not in text


def test_configure_managed_wsl2_runtime_inserts_missing_keys_before_next_section(
    tmp_path: Path,
) -> None:
    user_profile = tmp_path / "profile"
    user_profile.mkdir()
    wslconfig = user_profile / ".wslconfig"
    wslconfig.write_text(
        "# keep\n[wsl2]\nmemory=9GB\n\n[experimental]\nsparseVhd=true\n",
        encoding="utf-8",
    )
    payload = _run_confirmed_wsl_apply(user_profile, extra_args=["-AllowMergeExistingWslConfig"])
    text = wslconfig.read_text(encoding="utf-8")
    wsl2_block = text.split("[wsl2]", 1)[1].split("[experimental]", 1)[0]
    experimental_block = text.split("[experimental]", 1)[1]
    assert payload["apply_performed"] is True
    assert payload["final_wslconfig_verified"] is True
    assert payload["final_wslconfig_missing_keys"] == []
    assert "memory=5GB" in wsl2_block
    assert "processors=3" in wsl2_block
    assert "swap=2GB" in wsl2_block
    assert "autoMemoryReclaim=gradual" in wsl2_block
    assert "sparseVhd=true" in experimental_block


def test_configure_managed_wsl2_runtime_rejects_duplicate_wsl2_sections(
    tmp_path: Path,
) -> None:
    user_profile = tmp_path / "profile"
    user_profile.mkdir()
    wslconfig = user_profile / ".wslconfig"
    original = "[wsl2]\nmemory=4GB\n\n[experimental]\nsparseVhd=true\n\n[wsl2]\nprocessors=2\n"
    wslconfig.write_text(original, encoding="utf-8")
    payload = _run_confirmed_wsl_apply(
        user_profile,
        extra_args=["-AllowMergeExistingWslConfig"],
    )
    assert payload["apply_performed"] is False
    assert payload["reason_code"] == "duplicate_wsl2_section_requires_manual_cleanup"
    assert payload["duplicate_wsl2_sections"] is True
    assert wslconfig.read_text(encoding="utf-8") == original


def test_configure_managed_wsl2_runtime_rejects_duplicate_managed_keys(
    tmp_path: Path,
) -> None:
    user_profile = tmp_path / "profile"
    user_profile.mkdir()
    wslconfig = user_profile / ".wslconfig"
    original = "[wsl2]\nmemory=4GB\nmemory=5GB\nprocessors=2\n"
    wslconfig.write_text(original, encoding="utf-8")
    payload = _run_confirmed_wsl_apply(
        user_profile,
        extra_args=["-AllowMergeExistingWslConfig"],
    )
    assert payload["apply_performed"] is False
    assert payload["reason_code"] == "duplicate_wsl2_managed_key_requires_manual_cleanup"
    assert "memory" in payload["duplicate_wsl2_managed_keys"]
    assert wslconfig.read_text(encoding="utf-8") == original


def test_detect_hub_runtime_reports_wsl_policy_passively_without_switching_runtime(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    config = programdata / "config"
    config.mkdir(parents=True)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    policy_path = config / "managed_wsl2_runtime_policy.json"
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
            "-PlanOnly",
            "-OutputJson",
            str(policy_path),
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "4",
        ],
        env=env,
    )
    detected = json.loads(
        _run_powershell(
            ["-File", str(REPO_ROOT / "scripts" / "detect_hub_runtime.ps1")],
            env=env,
        ).stdout
    )
    assert detected["runtime_dependency_mode"] != "managed_wsl2_container_runtime_candidate"
    assert detected["agency_install_status"] == "NO_GO"
    assert detected["immoapp_wsl_policy_present"] is True
    assert detected["managed_wsl2_policy_status"] == "GO"


def _write_fake_wsl_command(
    bin_dir: Path,
    *,
    distro_name: str = "ImmoAppRuntime",
    identity_distro_name: str = "ImmoAppRuntime",
    container_engine_status: str = "GO",
    compose_status: str = "GO",
    docker_daemon_status: str = "GO",
    docker_info_status: str = "GO",
    image_archive_status: str = "GO",
    image_inventory_status: str = "GO",
    image_presence_status: str = "GO",
    compose_payload_status: str = "GO",
    compose_pull_policy_status: str = "GO",
    compose_up_status: str = "GO",
    compose_service_status: str = "GO",
    service_readiness_elapsed_seconds: int = 3,
    caddy_bind_mode: str = "local",
    service_status: str = "GO",
    reason_code: str | None = None,
    hang_service_command: bool = False,
) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    programdata = bin_dir.parent / "ProgramData" / "ImmoApp"
    archive, archive_sha, inventory, inventory_sha = _write_fake_managed_image_bundle(programdata)
    effective_reason = reason_code
    if effective_reason is None:
        effective_reason = (
            "hub_backend_services_unhealthy_or_timeout"
            if service_status != "GO"
            else "managed_wsl2_runtime_start_go"
        )
    effective_compose_service_status = (
        "NO-GO"
        if service_status != "GO" and compose_service_status == "GO"
        else compose_service_status
    )
    identity = json.dumps(
        {
            "kind": "immoapp_managed_wsl2_runtime_identity",
            "schema_version": 1,
            "distro_name": identity_distro_name,
            "runtime_identity": "ImmoAppRuntime",
            "container_engine_status": container_engine_status,
            "docker_info_status": docker_info_status,
            "compose_cli_status": compose_status,
            "compose_status": compose_status,
            "service_status": service_status,
            "services": [
                {"name": "caddy", "status": "GO"},
                {"name": "web", "status": "GO"},
            ],
        },
        separators=(",", ":"),
    )
    identity_file = bin_dir / "identity.json"
    identity_file.write_text(identity, encoding="utf-8")
    service = json.dumps(
        {
            "kind": "immoapp_managed_wsl2_runtime_service_evidence",
            "schema_version": 1,
            "distro_identity_status": "GO",
            "docker_daemon_status": docker_daemon_status,
            "docker_info_status": docker_info_status,
            "compose_cli_status": compose_status,
            "image_archive_status": image_archive_status,
            "image_inventory_status": image_inventory_status,
            "image_load_status": "not_needed",
            "image_presence_status": image_presence_status,
            "compose_payload_status": compose_payload_status,
            "compose_pull_policy_status": compose_pull_policy_status,
            "compose_up_status": compose_up_status,
            "compose_service_status": effective_compose_service_status,
            "service_status": service_status,
            "front_door_partial_status": "GO",
            "front_door_health_status": "GO",
            "reason_code": effective_reason,
            "image_archive_path": str(archive),
            "image_archive_host_path": str(archive),
            "image_archive_wsl_path": "/mnt/c/ProgramData/ImmoApp/runtime/images/immoapp-runtime-images.tar",
            "image_archive_sha256": archive_sha,
            "image_bundle_inventory_path": str(inventory),
            "image_bundle_inventory_host_path": str(inventory),
            "image_bundle_inventory_wsl_path": (
                "/mnt/c/ProgramData/ImmoApp/config/"
                "managed_wsl2_runtime_image_bundle_inventory.json"
            ),
            "image_bundle_inventory_sha256": inventory_sha,
            "compose_file": "/opt/immoapp/runtime/compose/compose.yaml",
            "compose_project": "immoapp-managed-hub",
            "docker_start_attempted": False,
            "docker_start_timeout_seconds": 45,
            "docker_start_elapsed_seconds": 0,
            "docker_start_exit_code": "",
            "docker_start_diagnostics": "",
            "service_readiness_timeout_seconds": 300,
            "service_readiness_elapsed_seconds": service_readiness_elapsed_seconds,
            "caddy_bind_host": "127.0.0.1" if caddy_bind_mode == "local" else "0.0.0.0",
            "caddy_bind_mode": caddy_bind_mode,
            "services": [
                {
                    "name": "caddy",
                    "state": "running" if service_status == "GO" else "missing",
                    "health": "",
                    "status": "GO" if service_status == "GO" else "NO-GO",
                },
                {
                    "name": "web",
                    "state": "running" if service_status == "GO" else "missing",
                    "health": "healthy" if service_status == "GO" else "",
                    "status": "GO" if service_status == "GO" else "NO-GO",
                },
            ],
            "failing_services": (
                []
                if service_status == "GO"
                else [{"service": "web", "state": "missing", "reason": "service_missing"}]
            ),
            "proof_result": "GO" if service_status == "GO" else "NO-GO",
            "agency_install_status": "NO_GO",
            "public_beta_status": "NO_GO",
        },
        separators=(",", ":"),
    )
    service_file = bin_dir / "service.json"
    service_file.write_text(service, encoding="utf-8")
    fake_wsl_py = bin_dir / "fake_wsl.py"
    fake_wsl_py.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import pathlib, sys, time",
                f"identity_file = pathlib.Path({str(identity_file)!r})",
                f"service_file = pathlib.Path({str(service_file)!r})",
                f"distro_name = {distro_name!r}",
                f"hang_service_command = {hang_service_command!r}",
                "args = sys.argv[1:]",
                "joined = ' '.join(args)",
                "if args[:1] == ['--status']:",
                "    print('Default Version: 2')",
                "    raise SystemExit(0)",
                "if args[:1] == ['--version']:",
                "    print('WSL version: 2.1.5')",
                "    raise SystemExit(0)",
                "if args[:2] == ['-l', '-q'] or args[:1] == ['-l']:",
                "    if distro_name:",
                "        print(distro_name)",
                "    raise SystemExit(0)",
                "if '-d' in args and 'sh' in args and '-lc' not in args:",
                "    print('managed_wsl2_runtime_payload_update_go')",
                "    raise SystemExit(0)",
                "if '/opt/immoapp/runtime/bin/immoapp-runtime-identity' in joined:",
                "    if '--json' in args:",
                "        print(identity_file.read_text(encoding='utf-8'), end='')",
                "        raise SystemExit(0)",
                "    print('managed_wsl2_runtime_identity_args_not_split')",
                "    raise SystemExit(44)",
                "if hang_service_command and '/opt/immoapp/runtime/bin/start-managed-hub' in joined:",
                "    time.sleep(30)",
                "    raise SystemExit(0)",
                "print(service_file.read_text(encoding='utf-8'), end='')",
                "raise SystemExit(0)",
            ]
        ),
        encoding="utf-8",
    )
    (bin_dir / "wsl.cmd").write_text(
        "\n".join(
            [
                "@echo off",
                f'"{sys.executable}" "{fake_wsl_py}" %*',
                "exit /b %ERRORLEVEL%",
            ]
        ),
        encoding="utf-8",
    )


def _write_fake_official_rootfs_builder_wsl(
    bin_dir: Path, *, fail_cleanup_unregister: bool = False
) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "fake_official_rootfs_wsl.py"
    state = bin_dir / "distros.txt"
    exported = bin_dir / "exported.txt"
    fail_flag = bin_dir / "fail-cleanup-unregister.txt"
    if fail_cleanup_unregister:
        fail_flag.write_text("1", encoding="utf-8")
    script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import io",
                "import sys",
                "import tarfile",
                "from pathlib import Path",
                f"STATE = Path({str(state)!r})",
                f"EXPORTED = Path({str(exported)!r})",
                f"FAIL_FLAG = Path({str(fail_flag)!r})",
                f"REQUIRED = {list(MANAGED_WSL2_ROOTFS_REQUIRED_ENTRIES)!r}",
                "def distros() -> list[str]:",
                "    if not STATE.exists():",
                "        return []",
                "    return [line.strip() for line in STATE.read_text().splitlines() if line.strip()]",
                "def write_distros(values: list[str]) -> None:",
                "    if values:",
                "        STATE.write_text('\\n'.join(values) + '\\n')",
                "    elif STATE.exists():",
                "        STATE.unlink()",
                "def write_tar(path: str) -> None:",
                "    Path(path).parent.mkdir(parents=True, exist_ok=True)",
                "    with tarfile.open(path, 'w') as bundle:",
                "        for name in REQUIRED:",
                "            data = b'#!/bin/sh\\nexit 0\\n'",
                "            info = tarfile.TarInfo(name)",
                "            info.mode = 0o755",
                "            info.size = len(data)",
                "            bundle.addfile(info, io.BytesIO(data))",
                "        data = b'ID=ubuntu\\nVERSION_CODENAME=noble\\n'",
                "        info = tarfile.TarInfo('etc/os-release')",
                "        info.size = len(data)",
                "        bundle.addfile(info, io.BytesIO(data))",
                "args = sys.argv[1:]",
                "if args[:2] == ['-l', '-q']:",
                "    sys.stdout.write('\\n'.join(distros()))",
                "    sys.exit(0)",
                "if args[:1] in (['--status'], ['--version'], ['--shutdown']):",
                "    sys.exit(0)",
                "if args[:1] == ['--terminate']:",
                "    sys.exit(0)",
                "if args[:1] == ['--import']:",
                "    values = distros()",
                "    if args[1] not in values:",
                "        values.append(args[1])",
                "    write_distros(values)",
                "    sys.exit(0)",
                "if args[:1] == ['--export']:",
                "    write_tar(args[2])",
                "    EXPORTED.write_text('1')",
                "    sys.exit(0)",
                "if args[:1] == ['--unregister']:",
                "    if FAIL_FLAG.exists() and EXPORTED.exists() and args[1] == 'ImmoAppRuntimeBuild':",
                "        print('simulated cleanup unregister failure', file=sys.stderr)",
                "        sys.exit(51)",
                "    write_distros([d for d in distros() if d != args[1]])",
                "    sys.exit(0)",
                "if args[:1] == ['-d']:",
                "    command = ' '.join(args)",
                "    if 'immoapp-runtime-identity --json' in command:",
                '        print(\'{"kind":"immoapp_managed_wsl2_runtime_identity","schema_version":1,"distro_name":"ImmoAppRuntimeBuild","runtime_identity":"ImmoAppRuntime","runtime_root":"/opt/immoapp/runtime","container_engine_kind":"docker_engine","container_engine_version":"Docker version 29.5.3, build test","container_engine_status":"GO","compose_status":"GO","compose_version":"Docker Compose version v5.1.4","log_policy_status":"GO","service_status":"NO-GO","agency_install_status":"NO_GO"}\')',
                "    sys.exit(0)",
                "sys.exit(0)",
            ]
        ),
        encoding="utf-8",
    )
    command = bin_dir / "wsl.cmd"
    command.write_text(
        "@echo off\r\n" f'"{sys.executable}" "{script}" %*\r\n',
        encoding="utf-8",
    )
    return command


class _FrontDoorHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/health/":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/v1/hub/front-door/identity/":
            body = b'{"kind":"immoapp_hub_front_door_identity","schema_version":1}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-ImmoApp-Front-Door", "caddy")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def _run_front_door_fixture() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FrontDoorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_client_endpoint_script_falls_back_without_client_venv_after_front_door_probe(
    tmp_path: Path,
) -> None:
    server, url = _run_front_door_fixture()
    appdata_root = tmp_path / "ImmoApp"
    try:
        result = _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "set_client_api_endpoint.ps1"),
                "-BaseUrl",
                url,
                "-AllowLocalHub",
                "-ConnectionSource",
                "local_hub",
            ],
            env={"IMMOAPP_APPDATA_ROOT": str(appdata_root)},
            timeout=30,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0
    assert "Client API endpoint verified through Hub front door" in result.stdout
    config = json.loads((appdata_root / "config" / "client_api.json").read_text())
    assert config["base_url"] == url
    assert config["connection_source"] == "local_hub"
    assert "password" not in config
    assert "token" not in config


def test_client_endpoint_script_falls_back_when_installed_package_has_no_python_sources(
    tmp_path: Path,
) -> None:
    server, url = _run_front_door_fixture()
    appdata_root = tmp_path / "ImmoApp"
    installed_scripts = tmp_path / "Installed" / "scripts"
    installed_scripts.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "common.ps1", installed_scripts / "common.ps1")
    shutil.copy2(
        REPO_ROOT / "scripts" / "set_client_api_endpoint.ps1",
        installed_scripts / "set_client_api_endpoint.ps1",
    )
    fake_python = appdata_root / "venvs" / "immoapp-client-py314" / "Scripts" / "python.exe"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("not a real executable", encoding="utf-8")
    try:
        result = _run_powershell(
            [
                "-File",
                str(installed_scripts / "set_client_api_endpoint.ps1"),
                "-BaseUrl",
                url,
                "-AllowLocalHub",
                "-ConnectionSource",
                "local_hub",
            ],
            env={"IMMOAPP_APPDATA_ROOT": str(appdata_root)},
            timeout=30,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0
    config = json.loads((appdata_root / "config" / "client_api.json").read_text())
    assert config["base_url"] == url
    assert config["connection_source"] == "local_hub"


def test_wsl_candidate_provider_registration_requires_config_plan(tmp_path: Path) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    config = programdata / "config"
    logs = programdata / "logs"
    config.mkdir(parents=True)
    logs.mkdir(parents=True)
    policy = config / "managed_wsl2_runtime_policy.json"
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "managed_wsl2_runtime_policy.ps1"),
            "-PlanOnly",
            "-OutputJson",
            str(policy),
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "8",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "register_managed_hub_runtime_provider.ps1"),
            "-RuntimeDependencyMode",
            "managed_wsl2_container_runtime_candidate",
            "-WslPolicyJsonPath",
            str(policy),
            "-ConfirmManagedRuntimeProof",
            "-AllowTestOnlyPath",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    assert "wsl_config_plan_json_missing" in (result.stderr + result.stdout)
    assert not (config / "hub_runtime_provider.json").exists()


def test_hub_manager_install_runtime_candidate_requires_confirmation(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "logs" / "managed_wsl2_runtime_candidate_install.json"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "install-runtime-candidate",
    )

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "install-runtime-candidate",
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "8",
            *owner_evidence_args,
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "confirm_install_runtime_candidate_required" in (result.stderr + result.stdout)
    assert not (programdata / "config" / "hub_runtime_provider.json").exists()


def test_hub_manager_install_runtime_candidate_refuses_existing_non_candidate_provider(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    config = programdata / "config"
    config.mkdir(parents=True)
    provider = config / "hub_runtime_provider.json"
    provider_payload = {
        "kind": "immoapp_hub_runtime_provider",
        "schema_version": 1,
        "provider_mode": "managed_container_runtime",
        "runtime_dependency_mode": "managed_container_runtime",
        "proof_only": False,
    }
    provider.write_text(json.dumps(provider_payload, sort_keys=True), encoding="utf-8")
    original_bytes = provider.read_bytes()
    output = programdata / "logs" / "managed_wsl2_runtime_candidate_install.json"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "install-runtime-candidate",
    )

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "install-runtime-candidate",
            "-ConfirmInstallRuntimeCandidate",
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "8",
            *owner_evidence_args,
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert provider.read_bytes() == original_bytes
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["candidate_overwrite_refused"] is True
    assert payload["existing_provider_present"] is True
    assert payload["existing_provider_mode"] == "managed_container_runtime"
    assert payload["existing_provider_preserved"] is True
    assert payload["candidate_registration_status"] == "NO-GO"
    assert payload["reason_code"] == (
        "existing_managed_runtime_provider_refuses_candidate_overwrite"
    )


def test_hub_manager_installs_managed_wsl2_candidate_provider_and_detection(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "logs" / "managed_wsl2_runtime_candidate_install.json"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "install-runtime-candidate",
    )

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "install-runtime-candidate",
            "-ConfirmInstallRuntimeCandidate",
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "8",
            *owner_evidence_args,
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "NO-GO"
    assert payload["proof_scope"] == "registration_only"
    assert payload["candidate_registration_status"] == "GO"
    assert payload["internal_candidate_status"] == "GO"
    assert payload["agency_install_status"] == "NO_GO"
    assert payload["runtime_artifact_status"] == "NO-GO"
    assert payload["runtime_start_status"] == "NO-GO"
    assert payload["runtime_start_reason_code"] == "managed_wsl2_runtime_artifact_missing"
    provider = programdata / "config" / "hub_runtime_provider.json"
    provider_payload = json.loads(provider.read_text(encoding="utf-8-sig"))
    assert provider_payload["provider_mode"] == "managed_wsl2_container_runtime_candidate"
    assert provider_payload["runtime_dependency_mode"] == "managed_wsl2_container_runtime_candidate"
    assert provider_payload["proof_only"] is True
    assert provider_payload["wsl_policy_json_path"]
    assert provider_payload["wsl_config_plan_json_path"]
    detection = payload["runtime_detection"]
    assert detection["runtime_dependency_mode"] == "managed_wsl2_container_runtime_candidate"
    assert detection["provider_validation_status"] == "valid"
    assert detection["internal_proof_status"] == "GO"
    assert detection["agency_install_status"] == "NO_GO"
    assert detection["reason_code"] == "managed_wsl2_runtime_artifact_missing"


def test_hub_manager_install_runtime_candidate_allows_existing_candidate_refresh(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    first_output = programdata / "logs" / "candidate-first.json"
    second_output = programdata / "logs" / "candidate-second.json"
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "install-runtime-candidate",
    )
    command = [
        "-File",
        str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
        "-Action",
        "install-runtime-candidate",
        "-ConfirmInstallRuntimeCandidate",
        "-MachineTotalMemoryGb",
        "16",
        "-MachineLogicalProcessors",
        "8",
        *owner_evidence_args,
    ]

    _run_powershell([*command, "-OutputJson", str(first_output)], env=env)
    _run_powershell([*command, "-OutputJson", str(second_output)], env=env)

    payload = json.loads(second_output.read_text(encoding="utf-8-sig"))
    provider = json.loads(
        (programdata / "config" / "hub_runtime_provider.json").read_text(encoding="utf-8-sig")
    )
    assert payload["existing_provider_present"] is True
    assert payload["existing_provider_mode"] == "managed_wsl2_container_runtime_candidate"
    assert payload["candidate_overwrite_refused"] is False
    assert payload["candidate_registration_status"] == "GO"
    assert payload["proof_result"] == "NO-GO"
    assert provider["provider_mode"] == "managed_wsl2_container_runtime_candidate"


def test_hub_manager_start_refuses_wsl_candidate_until_runtime_artifact_exists(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "install-runtime-candidate",
    )
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "install-runtime-candidate",
            "-ConfirmInstallRuntimeCandidate",
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "8",
            *owner_evidence_args,
            "-OutputJson",
            str(programdata / "logs" / "candidate.json"),
        ],
        env=env,
    )

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "start",
            "-HubBaseUrl",
            "http://127.0.0.1:9",
        ],
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "managed_wsl2_runtime_artifact_missing" in (result.stderr + result.stdout)


def test_build_managed_wsl2_runtime_artifact_creates_clean_inventory(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "config" / "managed_wsl2_runtime_artifact_inventory.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_artifact.ps1"),
            "-OutputJson",
            str(output),
            "-AllowTestOnlyPath",
        ],
        env=env,
    )

    payload = json.loads(result.stdout)
    inventory = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "GO"
    assert inventory["kind"] == "immoapp_managed_wsl2_runtime_artifact_inventory"
    assert inventory["runtime_dependency_mode"] == "managed_wsl2_container_runtime_artifact"
    assert inventory["runtime_artifact_status"] == "GO"
    assert inventory["runtime_start_status"] == "NO-GO"
    assert inventory["agency_install_status"] == "NO_GO"
    assert inventory["forbidden_path_count"] == 0
    assert (
        inventory["required_entries"]["bin/immoapp-managed-wsl2-runtime.ps1"]["status"] == "present"
    )
    assert (
        inventory["required_entries"]["bin/immoapp-managed-wsl2-compose.ps1"]["status"] == "present"
    )
    assert inventory["required_entries"]["bin/start-managed-hub.ps1"]["status"] == "present"
    assert inventory["required_entries"]["bin/status-managed-hub.ps1"]["status"] == "present"
    bridge = (
        programdata
        / "runtime"
        / "managed-wsl2-artifact"
        / "bin"
        / "immoapp-managed-wsl2-bridge.ps1"
    ).read_text(encoding="utf-8")
    assert "[string[]]$linuxArgs = @(" in bridge
    assert '"identity" { "/opt/immoapp/runtime/bin/immoapp-runtime-identity"; "--json" }' in bridge
    assert '"start" { "/opt/immoapp/runtime/bin/start-managed-hub" }' in bridge
    assert 'if ($Action -eq "start")' in bridge
    assert 'if ($Action -eq "restart" -and $exitCode -eq 0)' in bridge
    assert '"-d", $distroName, "--cd", "/opt/immoapp/runtime", "--"' in bridge
    assert "Start-Process" in bridge
    assert "-RedirectStandardOutput $stdoutPath" in bridge
    assert "-RedirectStandardError $stderrPath" in bridge
    assert "IMMOAPP_MANAGED_WSL2_ACTION_TIMEOUT_SECONDS" in bridge
    assert "managed_wsl2_runtime_bridge_timeout" in bridge
    assert ".WaitForExit([Math]::Max(1, $actionTimeoutSeconds) * 1000)" in bridge
    assert "-Wait `" not in bridge
    assert "2>&1" not in bridge
    assert "[System.IO.File]::ReadAllText($stderrPath)" in bridge
    assert '"/opt/immoapp/runtime/bin/immoapp-runtime-identity --json"' not in bridge
    assert "Get-ImmoAppManagedRuntimeEnvArgs" in bridge
    assert '"IMMOAPP_CADDY_BIND_HOST"' in bridge
    assert '"IMMOAPP_HUB_FRONT_DOOR_URL"' in bridge
    assert '@("env") + $runtimeEnvArgs + $linuxArgs' in bridge
    assert '"POSTGRES_PASSWORD"' not in bridge


def test_managed_wsl2_bridge_passes_whitelisted_front_door_env_only(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "config" / "managed_wsl2_runtime_artifact_inventory.json"
    env_file = programdata / "config" / ".env.local"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "\n".join(
            [
                "IMMOAPP_CADDY_BIND_HOST=0.0.0.0",
                "IMMOAPP_HUB_FRONT_DOOR_PORT=8000",
                "IMMOAPP_HUB_FRONT_DOOR_URL=http://192.168.100.17:8000",
                "IMMOAPP_PLATFORM_ADMIN_EMAIL=platform-admin@example.test",
                "IMMOAPP_PUBLIC_BASE_URL=http://192.168.100.17:8000",
                "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,web,caddy,LAPTOP,192.168.100.17",
                "POSTGRES_PASSWORD=must-not-cross-bridge",
            ]
        ),
        encoding="utf-8",
    )
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_artifact.ps1"),
            "-OutputJson",
            str(output),
            "-AllowTestOnlyPath",
        ],
        env=env,
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    args_path = fake_bin / "wsl-args.txt"
    identity = json.dumps(
        {
            "kind": "immoapp_managed_wsl2_runtime_identity",
            "schema_version": 1,
            "distro_name": "ImmoAppRuntime",
            "runtime_identity": "ImmoAppRuntime",
            "container_engine_status": "GO",
            "docker_info_status": "GO",
            "compose_cli_status": "GO",
            "compose_status": "GO",
            "service_status": "NO-GO",
            "agency_install_status": "NO_GO",
        },
        separators=(",", ":"),
    )
    (fake_bin / "wsl.cmd").write_text(
        "\n".join(
            [
                "@echo off",
                'if "%1"=="-l" echo ImmoAppRuntime& exit /b 0',
                f'echo %* > "{args_path}"',
                f"echo {identity}",
                "exit /b 0",
            ]
        ),
        encoding="utf-8",
    )
    bridge = (
        programdata
        / "runtime"
        / "managed-wsl2-artifact"
        / "bin"
        / "immoapp-managed-wsl2-bridge.ps1"
    )

    _run_powershell(
        ["-File", str(bridge), "-Action", "identity"],
        env={
            "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )

    args = args_path.read_text(encoding="utf-8")
    assert " env " in f" {args} "
    assert "IMMOAPP_CADDY_BIND_HOST=0.0.0.0" in args
    assert "IMMOAPP_HUB_FRONT_DOOR_PORT=8000" in args
    assert "IMMOAPP_HUB_FRONT_DOOR_URL=http://192.168.100.17:8000" in args
    assert "IMMOAPP_PLATFORM_ADMIN_EMAIL=platform-admin@example.test" in args
    assert "IMMOAPP_PUBLIC_BASE_URL=http://192.168.100.17:8000" in args
    assert "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,web,caddy,LAPTOP,192.168.100.17" in args
    assert "POSTGRES_PASSWORD" not in args
    assert "must-not-cross-bridge" not in args


def test_managed_wsl2_bridge_times_out_hanging_wsl_action(tmp_path: Path) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "config" / "managed_wsl2_runtime_artifact_inventory.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_artifact.ps1"),
            "-OutputJson",
            str(output),
            "-AllowTestOnlyPath",
        ],
        env=env,
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "wsl.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                'if "%1"=="-l" echo ImmoAppRuntime& exit /b 0',
                "ping 127.0.0.1 -n 10 > nul",
                "echo should-not-finish",
                "exit /b 0",
            ]
        )
        + "\r\n",
        encoding="ascii",
    )
    bridge = (
        programdata
        / "runtime"
        / "managed-wsl2-artifact"
        / "bin"
        / "immoapp-managed-wsl2-bridge.ps1"
    )

    result = _run_powershell(
        ["-File", str(bridge), "-Action", "status"],
        env={
            "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            "IMMOAPP_MANAGED_WSL2_ACTION_TIMEOUT_SECONDS": "2",
        },
        check=False,
        timeout=15,
    )

    assert result.returncode == 124
    assert "managed_wsl2_runtime_bridge_timeout" in (result.stderr + result.stdout)
    assert "status" in (result.stderr + result.stdout)


def test_build_managed_wsl2_runtime_artifact_rejects_forbidden_content(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    artifact_root = programdata / "runtime" / "managed-wsl2-artifact"
    artifact_root.mkdir(parents=True)
    (artifact_root / ".env").write_text("SECRET=value", encoding="utf-8")
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_artifact.ps1"),
            "-ArtifactRoot",
            str(artifact_root),
            "-OutputJson",
            str(programdata / "config" / "inventory.json"),
            "-AllowTestOnlyPath",
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "forbidden_sensitive_file" in (result.stderr + result.stdout)


def test_managed_wsl2_restart_refreshes_canonical_start_evidence_contract() -> None:
    manager = _read("scripts/hub_manager.ps1")
    detector = _read("scripts/detect_hub_runtime.ps1")

    assert '$ManagedAction -in @("start", "restart")' in manager
    assert '$startEvidenceAction -notin @("start", "restart")' in detector
    assert (
        'if ($startEvidenceAction -eq "restart") { $managedRestartCommandPath } '
        "else { $managedRuntimeCommandPath }" in detector
    )


def test_detect_hub_runtime_uses_safe_json_for_output_contract() -> None:
    detector = _read("scripts/detect_hub_runtime.ps1")
    assert "Write-ImmoAppSafeJson -Path $OutputJson" in detector
    assert "Set-Content -LiteralPath $OutputJson" not in detector


def test_build_managed_wsl2_runtime_rootfs_overlays_required_commands(
    tmp_path: Path,
) -> None:
    rootfs_builder = _read("scripts/build_managed_wsl2_runtime_rootfs.ps1")
    assert '$buildMethod = "direct_tar_overlay"' in rootfs_builder
    assert 'tarfile.open(base_path, "r:*")' in rootfs_builder
    assert 'tarfile.open(output_path, "r:")' in rootfs_builder
    assert 'key.startswith("GNU.sparse")' in rootfs_builder
    assert "member.sparse = None" in rootfs_builder
    assert '".pending-"' in rootfs_builder
    assert "Move-Item -LiteralPath $pendingOutputFull" in rootfs_builder
    assert "Resolve-ImmoAppPython" in rootfs_builder
    assert "AllowTestOnlyPath" in rootfs_builder
    assert "managed_wsl2_runtime_rootfs_dirty_source" in rootfs_builder
    assert "managed_wsl2_runtime_rootfs_source_commit_mismatch" in rootfs_builder
    assert "ImmoAppRuntimeOverlayBuild" not in rootfs_builder
    assert "wsl.exe" not in rootfs_builder.lower()
    assert "--import" not in rootfs_builder
    assert "--export" not in rootfs_builder
    assert "--unregister" not in rootfs_builder
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    base = tmp_path / "base-rootfs.tar"
    with tarfile.open(base, "w") as bundle:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        bundle.addfile(root)
        os_release = tarfile.TarInfo("etc/os-release")
        os_release.size = len(b"ID=immoapp-test\n")
        os_release.mode = 0o644
        bundle.addfile(os_release, io.BytesIO(b"ID=immoapp-test\n"))
    output_rootfs = programdata / "runtime" / "rootfs" / "ImmoAppRuntime.rootfs.tar"
    output = programdata / "config" / "managed_wsl2_runtime_rootfs_inventory.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_rootfs.ps1"),
            "-BaseRootfsTarPath",
            str(base),
            "-OutputRootfsTarPath",
            str(output_rootfs),
            "-OutputJson",
            str(output),
            "-AllowTestOnlyPath",
        ],
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["proof_result"] == "GO"
    assert payload["rootfs_artifact_status"] == "GO"
    assert payload["runtime_start_status"] == "NO-GO"
    assert payload["agency_install_status"] == "NO_GO"
    assert payload["build_method"] == "direct_tar_overlay"
    assert payload["build_mutated_wsl"] is False
    assert payload["build_invoked_docker"] is False
    assert payload["build_invoked_package_manager"] is False
    assert payload["archive_validation_status"] == "GO"
    assert payload["archive_entry_count"] >= len(MANAGED_WSL2_ROOTFS_REQUIRED_ENTRIES)
    assert payload["sparse_files_expanded"] == 0
    with tarfile.open(output_rootfs, "r") as bundle:
        entries = {member.name: member.mode for member in bundle.getmembers()}
    for entry in MANAGED_WSL2_ROOTFS_REQUIRED_ENTRIES:
        assert entry in entries
        if entry.startswith("opt/immoapp/runtime/bin/"):
            assert entries[entry] & 0o111
        else:
            assert not (entries[entry] & 0o111)
    assert "opt/immoapp/runtime/runtime-metadata.json" in entries


def test_managed_wsl2_runtime_rootfs_failed_rebuild_preserves_existing_artifact(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    base = tmp_path / "invalid-base-rootfs.tar"
    base.write_bytes(b"not-a-tar")
    output_rootfs = programdata / "runtime" / "rootfs" / "ImmoAppRuntime.rootfs.tar"
    output_rootfs.parent.mkdir(parents=True)
    previous_artifact = b"previous-known-good-rootfs"
    output_rootfs.write_bytes(previous_artifact)
    output = programdata / "config" / "managed_wsl2_runtime_rootfs_inventory.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_rootfs.ps1"),
            "-BaseRootfsTarPath",
            str(base),
            "-OutputRootfsTarPath",
            str(output_rootfs),
            "-OutputJson",
            str(output),
            "-AllowReplaceOutputRootfs",
            "-AllowTestOnlyPath",
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert output_rootfs.read_bytes() == previous_artifact
    assert not list(output_rootfs.parent.glob("*.pending-*"))
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "NO-GO"
    assert payload["rootfs_artifact_status"] == "NO-GO"


def test_managed_wsl2_runtime_compose_is_offline_local_image_only() -> None:
    compose = _read("deployment/managed-runtime/compose/compose.yaml")

    def service_body(service: str) -> str:
        service_block = re.search(
            rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
            compose,
            re.MULTILINE | re.DOTALL,
        )
        assert service_block, service
        return service_block.group("body")

    persistent_services = (
        "db",
        "rabbitmq",
        "valkey",
        "openbao",
        "minio",
        "clamav",
        "web",
        "worker",
        "worker-import",
        "worker-rebuild",
        "worker-match",
        "beat",
        "caddy",
    )
    for service in persistent_services:
        assert "restart: unless-stopped" in service_body(service), service
    for service in (
        "rabbitmq-init",
        "db-app-role-init",
        "openbao-seed",
        "db-schema-prepare",
        "minio-init",
        "app-data-init",
    ):
        assert 'restart: "no"' in service_body(service), service
    assert not re.search(r"^\s+build:", compose, re.MULTILINE)
    assert "pull_policy: never" in compose
    assert "BAO_TOKEN_FILE: /run/immoapp-secrets/openbao.token" in compose
    assert compose.count("BAO_APPROLE_FILE: /run/immoapp-secrets/openbao-approle.json") >= 7
    assert 'BAO_TOKEN: ""' in compose
    for line in compose.splitlines():
        if "BAO_TOKEN:" in line:
            assert line.strip() == 'BAO_TOKEN: ""'
    assert "openbao-init:" in compose
    assert "server -config=/openbao/config/openbao.hcl" in compose
    assert 'python", "-m", "server.secret_store.openbao_runtime_init"' in compose
    assert "openbao-seed:" in compose
    assert 'python", "-m", "server.secret_store.openbao_runtime_seed"' in compose
    assert "openbao-init:\n        condition: service_completed_successfully" in compose
    assert "openbao-seed:\n        condition: service_completed_successfully" in compose
    assert "db-app-role-init:" in compose
    assert "ALTER ROLE %I WITH PASSWORD %L NOSUPERUSER" in compose
    assert "db-schema-prepare:" in compose
    assert "python server/manage.py immoapp_db_prepare" in compose
    assert "db-schema-prepare:\n        condition: service_completed_successfully" in compose
    assert compose.count("IMMOAPP_SECRETS_PATH: secret/data/immoapp") >= 7
    assert compose.count("IMMOAPP_SECRETS_ALLOWLIST:") >= 6
    assert "POSTGRES_" in compose
    assert "RABBITMQ_" in compose
    assert "MINIO_" in compose
    assert compose.count("POSTGRES_HOST: db") >= 6
    assert compose.count("VALKEY_URL: redis://valkey:6379/1") >= 6
    assert (
        compose.count(
            "CELERY_BROKER_URL: amqp://${RABBITMQ_USER:-immoapp}:${RABBITMQ_PASSWORD:-change-before-start}@rabbitmq:5672//"
        )
        >= 6
    )
    assert compose.count("STORAGE_ENDPOINT_URL: http://minio:9000") >= 6
    assert compose.count("STORAGE_CLAMD_HOST: clamav") >= 6
    assert (
        compose.count(
            "DJANGO_ALLOWED_HOSTS: ${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost,web,caddy}"
        )
        >= 7
    )
    web_service = service_body("web")
    assert "IMMOAPP_PLATFORM_ADMIN_EMAIL: ${IMMOAPP_PLATFORM_ADMIN_EMAIL:-}" in web_service
    assert "IMMOAPP_PUBLIC_BASE_URL: ${IMMOAPP_PUBLIC_BASE_URL:-}" in web_service
    assert "-dev-root-token-id" not in compose
    assert "/run/immoapp-secrets/bao_token" not in compose
    assert "Root Token:" not in compose
    assert "Unseal Key:" not in compose
    common = _read("deployment/managed-runtime/bin/managed-hub-common")
    caddyfile = _read("deployment/managed-runtime/proxy/Caddyfile")
    start = _read("deployment/managed-runtime/bin/start-managed-hub")
    stop = _read("deployment/managed-runtime/bin/stop-managed-hub")
    health = _read("deployment/managed-runtime/bin/health-managed-hub")
    backup = _read("deployment/managed-runtime/bin/backup-managed-hub")
    keepalive = _read("deployment/managed-runtime/bin/keepalive-managed-hub")
    assert "run_compose_bootstrap_gates()" in common
    assert 'cd "$runtime_root"' in common
    assert common.index('cd "$runtime_root"') < common.index('"$@" >"$out" 2>&1')
    assert (
        'docker compose -f "$compose_file" -p "$project_name" up -d rabbitmq db valkey openbao minio clamav'
        in common
    )
    for service in ("openbao-init", "openbao-seed", "db-app-role-init", "db-schema-prepare"):
        assert service in common
    assert '--force-recreate --no-deps "$svc"' in common
    assert "check_compose_services_fast()" in common
    assert "ps --format json" in common
    readiness_block = common.split("wait_for_service_readiness() {", 1)[1].split(
        "wait_for_front_door_readiness() {", 1
    )[0]
    assert "check_compose_services_fast" in readiness_block
    assert "wait_for_front_door_readiness" in start
    assert 'services_json="$(json_services_fast)"' in start
    assert 'failures_json="$(json_failures_fast)"' in start
    assert "run_compose_bootstrap_gates" in start
    assert start.index("run_compose_bootstrap_gates") < start.index("run_compose_up")
    assert "managed_wsl2_runtime_bootstrap_gates_failed" in start
    assert "keepalive_pid_file" in common
    assert "stop_keepalive()" in common
    assert "stop_keepalive || true" in stop
    assert "managed-hub-keepalive.pid" in keepalive
    assert 'sleep "${IMMOAPP_MANAGED_KEEPALIVE_INTERVAL_SECONDS:-300}"' in keepalive
    assert "probe_front_door" in health
    assert "header_up Host web" in caddyfile
    assert "header_up X-Forwarded-Host {host}" in caddyfile
    assert "header_up X-Forwarded-Proto {scheme}" in caddyfile
    assert "check_compose_services_fast" in health
    assert "verify_image_bundle" not in health
    assert "ensure_images_present status" not in health
    assert "front_door_probe_url" in common
    assert "http://127.0.0.1:${IMMOAPP_HUB_FRONT_DOOR_PORT:-8000}" in common
    assert '"$front_door_probe_url/api/v1/health/"' in common
    assert '"$front_door_probe_url/api/v1/hub/front-door/identity/"' in common
    assert "down -v" not in common
    assert "--renew-anon-volumes" not in common
    assert "managed_wsl2_backup_go" in backup
    assert "managed_wsl2_backup_root_not_approved" in backup
    assert "/mnt/c/ProgramData/ImmoApp/backups/managed-runtime" in backup
    assert "pg_dump" in backup
    assert "mc mirror --overwrite" in backup
    assert "backup_bundle_sha256" in backup
    services: dict[str, list[str]] = {}
    in_services = False
    current: str | None = None
    for line in compose.splitlines():
        if line == "services:":
            in_services = True
            continue
        if in_services and line and not line.startswith(" "):
            break
        if not in_services:
            continue
        service_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if service_match:
            current = service_match.group(1)
            services[current] = []
            continue
        if current:
            services[current].append(line)

    assert services
    for service_name, block_lines in services.items():
        block = "\n".join(block_lines)
        assert "pull_policy: never" in block, service_name
        image_match = re.search(r"^\s+image:\s+([^\s]+)\s*$", block, re.MULTILINE)
        assert image_match, service_name
        assert image_match.group(1) in MANAGED_LOCAL_IMAGE_TAGS, service_name


def test_managed_wsl2_runtime_start_templates_do_not_pull_install_or_fallback() -> None:
    runtime_files = [
        REPO_ROOT / "deployment" / "managed-runtime" / "bin" / name
        for name in (
            "managed-hub-common",
            "start-managed-hub",
            "status-managed-hub",
            "health-managed-hub",
            "logs-managed-hub",
            "backup-managed-hub",
            "stop-managed-hub",
            "restart-managed-hub",
            "immoapp-runtime-identity",
        )
    ]
    runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    forbidden_patterns = (
        r"\bdocker\s+pull\b",
        r"\bapt(?:-get)?\s+install\b",
        r"\bwinget\b",
        r"\bchoco\b",
        r"\bstack\.ps1\b",
        r"Program Files[/\\]Docker",
        r"docker\.exe",
    )
    for pattern in forbidden_patterns:
        assert not re.search(pattern, runtime_text, re.IGNORECASE), pattern
    assert "docker_desktop_rejected" in runtime_text
    assert "daemon_timeout" in runtime_text
    assert "managed_wsl2_docker_daemon_start_timeout" in runtime_text
    assert "systemctl start docker --no-block" in runtime_text
    assert "service docker start >/dev/null" not in runtime_text
    assert "docker_start_attempted" in runtime_text
    assert "docker_start_timeout_seconds" in runtime_text
    assert "wait_for_service_readiness" in runtime_text
    assert "hub_backend_services_unhealthy_or_timeout" in runtime_text
    assert "ensure_runtime_secrets" in runtime_text
    assert "openbao_token_file" in runtime_text
    assert "openbao_unseal_file" in runtime_text
    assert "openbao_approle_file" in runtime_text
    assert 'chmod 755 "$runtime_secrets_dir"' in runtime_text
    assert 'chmod 600 "$openbao_token_file"' in runtime_text
    assert 'chmod 600 "$openbao_unseal_file"' in runtime_text
    assert 'chmod 644 "$openbao_approle_file"' in runtime_text
    assert "/bao_token" not in runtime_text
    assert "loaded_image_archive_marker" in runtime_text
    assert 'marker_sha" != "$image_archive_sha256"' in runtime_text
    assert "image_archive_wsl_path" in runtime_text
    assert "managed_runtime_image_archive_wsl_path_missing" in runtime_text
    assert "caddy_bind_mode" in runtime_text
    assert "run_identity_with_timeout" in runtime_text
    assert "identity_timeout_seconds" in runtime_text
    assert "managed_wsl2_runtime_identity_timeout" in runtime_text
    assert "managed_wsl2_runtime_stop_failed" in runtime_text
    assert "managed_wsl2_runtime_logs_failed" in runtime_text


def test_managed_wsl2_image_bundle_sources_are_pinned() -> None:
    script = _read("scripts/build_managed_wsl2_runtime_image_bundle.ps1")
    compose = _read("deployment/managed-runtime/compose/compose.yaml")
    dockerfile = _read("deployment/docker/Dockerfile")

    assert not re.search(r'source\s*=\s*"[^"]*:latest"', script)
    assert ":latest" not in compose
    assert "managed_runtime_image_source_not_pinned" in script
    assert "managed_runtime_app_image_commit_mismatch" in script
    assert "org.opencontainers.image.revision" in script
    assert "IMMOAPP_SOURCE_COMMIT_SHA" in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile
    assert "image_archive_host_path" in script
    assert "image_archive_wsl_path" in script
    assert "image_bundle_inventory_host_path" in script
    assert "image_bundle_inventory_wsl_path" in script


def test_managed_wsl2_image_bundle_rejects_missing_app_image_revision_label(
    tmp_path: Path,
) -> None:
    source_commit = "a" * 40
    result, payload, _log = _run_image_bundle_builder_with_fake_docker(
        tmp_path,
        app_revision_label=None,
        source_commit_sha=source_commit,
    )

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "managed_runtime_app_image_commit_mismatch"
    assert payload["app_image_revision_verified"] is False
    assert payload["docker_save_invoked"] is False
    assert not (tmp_path / "ProgramData" / "ImmoApp" / "runtime" / "images").exists()


def test_managed_wsl2_image_bundle_rejects_wrong_app_image_revision_label(
    tmp_path: Path,
) -> None:
    source_commit = "a" * 40
    result, payload, _log = _run_image_bundle_builder_with_fake_docker(
        tmp_path,
        app_revision_label="b" * 40,
        source_commit_sha=source_commit,
    )

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "managed_runtime_app_image_commit_mismatch"
    assert payload["app_image_revision_verified"] is False
    assert payload["docker_save_invoked"] is False


def test_managed_wsl2_image_bundle_accepts_matching_app_image_revision_label(
    tmp_path: Path,
) -> None:
    source_commit = "a" * 40
    result, payload, _log = _run_image_bundle_builder_with_fake_docker(
        tmp_path,
        app_revision_label=source_commit,
        source_commit_sha=source_commit,
    )

    assert result.returncode == 0
    assert payload["proof_result"] == "GO"
    assert payload["reason_code"] == "managed_runtime_image_bundle_built"
    assert payload["app_image_source_commit_sha"] == source_commit
    assert payload["app_image_revision_label"] == "org.opencontainers.image.revision"
    assert payload["app_image_revision_verified"] is True
    assert payload["docker_save_invoked"] is True
    assert payload["images"]


def test_managed_wsl2_image_bundle_build_app_image_passes_revision_label(
    tmp_path: Path,
) -> None:
    source_commit = "a" * 40
    result, payload, log = _run_image_bundle_builder_with_fake_docker(
        tmp_path,
        app_revision_label=source_commit,
        source_commit_sha=source_commit,
        build_app_image=True,
    )

    assert result.returncode == 0
    assert payload["proof_result"] == "GO"
    log_text = log.read_text(encoding="utf-8")
    assert "--build-arg IMMOAPP_SOURCE_COMMIT_SHA=" + source_commit in log_text
    assert "--label org.opencontainers.image.revision=" + source_commit in log_text


def test_managed_wsl2_image_bundle_build_app_image_accepts_successful_stderr_progress(
    tmp_path: Path,
) -> None:
    source_commit = "a" * 40
    result, payload, _log = _run_image_bundle_builder_with_fake_docker(
        tmp_path,
        app_revision_label=source_commit,
        source_commit_sha=source_commit,
        build_app_image=True,
        build_progress_on_stderr=True,
    )

    assert result.returncode == 0
    assert payload["proof_result"] == "GO"
    assert payload["reason_code"] == "managed_runtime_image_bundle_built"
    assert payload["app_image_revision_verified"] is True


def test_managed_wsl2_image_bundle_build_app_image_with_unavailable_docker_is_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker.cmd"
    docker.write_text(
        "\r\n".join(
            [
                "@echo off",
                "echo docker unavailable 1>&2",
                "exit /b 127",
            ]
        )
        + "\r\n",
        encoding="ascii",
    )
    archive = programdata / "runtime" / "images" / "immoapp-runtime-images.tar"
    inventory = programdata / "config" / "managed_wsl2_runtime_image_bundle_inventory.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_image_bundle.ps1"),
            "-DockerExe",
            str(docker),
            "-SourceCommitSha",
            "a" * 40,
            "-OutputArchivePath",
            str(archive),
            "-OutputJson",
            str(inventory),
            "-BuildAppImage",
            "-AllowTestOnlyPath",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    payload = json.loads(inventory.read_text(encoding="utf-8-sig"))

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "managed_runtime_image_bundle_build_failed"
    assert payload["docker_save_invoked"] is False
    assert payload["image_archive_sha256"] == ""
    assert not archive.exists()
    assert "docker unavailable" in payload["failure_reason"]


def test_managed_wsl2_image_bundle_inventory_missing_archive_is_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    archive, _archive_sha, inventory, inventory_sha = _write_fake_managed_image_bundle(programdata)
    archive.unlink()

    result = _run_image_bundle_inventory_validator(
        programdata,
        inventory,
        expected_inventory_sha=inventory_sha,
        check=False,
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "managed_runtime_image_archive_missing" in payload["error"]


def test_managed_wsl2_image_bundle_inventory_hash_mismatch_is_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    archive, _archive_sha, inventory, inventory_sha = _write_fake_managed_image_bundle(programdata)
    archive.write_bytes(b"changed-image-archive")

    result = _run_image_bundle_inventory_validator(
        programdata,
        inventory,
        expected_inventory_sha=inventory_sha,
        check=False,
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "managed_runtime_image_archive_hash_mismatch" in payload["error"]


def test_managed_wsl2_stop_reports_no_go_when_compose_down_fails(tmp_path: Path) -> None:
    result = _run_managed_runtime_shell_script(
        tmp_path,
        "stop-managed-hub",
        fail_compose_action="down",
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "managed_wsl2_runtime_stop_failed"


def test_managed_wsl2_logs_reports_no_go_when_collection_fails(tmp_path: Path) -> None:
    result = _run_managed_runtime_shell_script(
        tmp_path,
        "logs-managed-hub",
        fail_compose_action="logs",
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["proof_result"] == "NO-GO"
    assert payload["logs_status"] == "NO-GO"
    assert payload["reason_code"] == "managed_wsl2_runtime_logs_failed"


def test_managed_wsl2_identity_does_not_probe_daemon_before_start(tmp_path: Path) -> None:
    sh = Path("C:/Program Files/Git/usr/bin/sh.exe")
    runtime_root = tmp_path / "runtime"
    fake_bin = tmp_path / "fake-bin"
    calls = tmp_path / "docker-calls.log"
    fake_bin.mkdir(parents=True)
    docker = fake_bin / "docker"
    docker.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                f'printf "%s\\n" "$*" >> "{_git_sh_path(calls)}"',
                'if [ "$1" = "--version" ]; then echo "Docker version fake"; exit 0; fi',
                'if [ "$1" = "compose" ] && [ "$2" = "version" ]; then echo "Docker Compose version fake"; exit 0; fi',
                'if [ "$1" = "info" ]; then while :; do sleep 1; done; fi',
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_git_sh_path(fake_bin)}:/usr/bin:/bin",
            "IMMOAPP_RUNTIME_ROOT": _git_sh_path(runtime_root),
            "IMMOAPP_RUNTIME_IDENTITY_TIMEOUT_SECONDS": "2",
            "WSL_DISTRO_NAME": "ImmoAppRuntime",
        }
    )

    result = subprocess.run(
        [
            str(sh),
            _git_sh_path(
                REPO_ROOT / "deployment" / "managed-runtime" / "bin" / "immoapp-runtime-identity"
            ),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["container_engine_status"] == "GO"
    assert payload["docker_info_status"] == "not_checked_pre_start"
    assert payload["compose_status"] == "GO"
    assert payload["reason_code"] == "managed_wsl2_runtime_identity_cli_go"
    assert "info" not in calls.read_text(encoding="utf-8")


def test_managed_wsl2_identity_cli_timeout_is_bounded(tmp_path: Path) -> None:
    sh = Path("C:/Program Files/Git/usr/bin/sh.exe")
    runtime_root = tmp_path / "runtime"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True)
    docker = fake_bin / "docker"
    docker.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "--version" ]; then while :; do sleep 1; done; fi',
                'if [ "$1" = "compose" ] && [ "$2" = "version" ]; then echo "Docker Compose version fake"; exit 0; fi',
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_git_sh_path(fake_bin)}:/usr/bin:/bin",
            "IMMOAPP_RUNTIME_ROOT": _git_sh_path(runtime_root),
            "IMMOAPP_RUNTIME_IDENTITY_TIMEOUT_SECONDS": "2",
            "WSL_DISTRO_NAME": "ImmoAppRuntime",
        }
    )

    try:
        result = subprocess.run(
            [
                str(sh),
                _git_sh_path(
                    REPO_ROOT
                    / "deployment"
                    / "managed-runtime"
                    / "bin"
                    / "immoapp-runtime-identity"
                ),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
    finally:
        _stop_processes_with_command_fragment(fake_bin)

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["reason_code"] == "managed_wsl2_runtime_identity_timeout"
    assert payload["identity_timed_out"] is True
    assert payload["identity_timeout_seconds"] == 2


def test_managed_wsl2_canonical_host_path_converts_to_wsl_path() -> None:
    command = (
        f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
        "$go = Convert-ImmoAppManagedWsl2CanonicalHostPathToWslPath "
        "-Path 'C:\\ProgramData\\ImmoApp\\runtime\\images\\immoapp-runtime-images.tar'; "
        "try { "
        "Convert-ImmoAppManagedWsl2CanonicalHostPathToWslPath "
        "-Path 'D:\\Other\\immoapp-runtime-images.tar' | Out-Null; "
        "$bad = 'NO_ERROR' "
        "} catch { $bad = [string]$_.Exception.Message }; "
        "[ordered]@{ go = $go; bad = $bad } | ConvertTo-Json -Depth 4"
    )
    result = _run_powershell(["-Command", command])
    payload = json.loads(result.stdout)

    assert payload["go"] == "/mnt/c/ProgramData/ImmoApp/runtime/images/immoapp-runtime-images.tar"
    assert "managed_runtime_image_archive_wsl_path_missing" in payload["bad"]


def test_build_managed_wsl2_runtime_rootfs_requires_explicit_base(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "config" / "managed_wsl2_runtime_rootfs_inventory.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_wsl2_runtime_rootfs.ps1"),
            "-OutputJson",
            str(output),
            "-OutputRootfsTarPath",
            str(programdata / "runtime" / "rootfs" / "ImmoAppRuntime.rootfs.tar"),
            "-AllowTestOnlyPath",
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "managed_wsl2_base_rootfs_tar_path_required"
    assert payload["runtime_start_status"] == "NO-GO"


def test_build_official_managed_wsl2_runtime_rootfs_rejects_unofficial_url(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"

    result, payload = _run_official_rootfs_builder(
        programdata,
        "-BaseRootfsUrl",
        "https://example.com/not-ubuntu-rootfs.tar.xz",
        check=False,
    )

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "official_rootfs_url_not_approved"
    assert payload["runtime_start_status"] == "NO-GO"
    assert payload["agency_install_status"] == "NO_GO"


def test_build_official_managed_wsl2_runtime_rootfs_rejects_sha_mismatch(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    source = (
        programdata
        / "runtime"
        / "rootfs"
        / "sources"
        / "ubuntu-24.04-minimal-cloudimg-amd64-root.tar"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not the expected rootfs")

    result, payload = _run_official_rootfs_builder(
        programdata,
        "-SourceRootfsTarPath",
        str(source),
        "-ExpectedBaseRootfsSha256",
        "0" * 64,
        check=False,
    )

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "official_rootfs_sha256_mismatch"
    assert payload["runtime_start_status"] == "NO-GO"


def test_build_official_managed_wsl2_runtime_rootfs_refuses_existing_build_distro(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    source = (
        programdata
        / "runtime"
        / "rootfs"
        / "sources"
        / "ubuntu-24.04-minimal-cloudimg-amd64-root.tar"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"base rootfs placeholder")
    fake_bin = tmp_path / "fake-bin"
    _write_fake_wsl_command(fake_bin, distro_name="ImmoAppRuntimeBuild")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()

    result, payload = _run_official_rootfs_builder(
        programdata,
        "-SourceRootfsTarPath",
        str(source),
        "-ExpectedBaseRootfsSha256",
        sha,
        "-ConfirmBuild",
        check=False,
        env={"IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd")},
    )

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "official_rootfs_build_distro_exists_replace_not_confirmed"
    assert payload["build_distro_name"] == "ImmoAppRuntimeBuild"
    assert payload["mutation_performed"] is False
    assert payload["runtime_start_status"] == "NO-GO"


def test_build_official_managed_wsl2_runtime_rootfs_cleans_build_distro_by_default(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    source = (
        programdata
        / "runtime"
        / "rootfs"
        / "sources"
        / "ubuntu-24.04-minimal-cloudimg-amd64-root.tar"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"base rootfs placeholder")
    fake_bin = tmp_path / "fake-bin"
    fake_wsl = _write_fake_official_rootfs_builder_wsl(fake_bin)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()

    _, payload = _run_official_rootfs_builder(
        programdata,
        "-SourceRootfsTarPath",
        str(source),
        "-ExpectedBaseRootfsSha256",
        sha,
        "-ConfirmBuild",
        env={"IMMOAPP_TEST_WSL_EXE": str(fake_wsl)},
    )

    assert payload["proof_result"] == "GO"
    assert payload["output_rootfs_tar_sha256"]
    assert payload["build_distro_cleanup_attempted"] is True
    assert payload["build_distro_cleanup_status"] == "GO"
    assert payload["build_distro_present_after_cleanup"] is False
    rootfs_inventory_path = programdata / "config" / "managed_wsl2_runtime_rootfs_inventory.json"
    rootfs_inventory = json.loads(rootfs_inventory_path.read_text(encoding="utf-8-sig"))
    assert payload["rootfs_inventory_path"] == str(rootfs_inventory_path)
    assert payload["rootfs_inventory_sha256"]
    assert rootfs_inventory["kind"] == "immoapp_managed_wsl2_runtime_rootfs_inventory"
    assert rootfs_inventory["proof_result"] == "GO"
    assert rootfs_inventory["output_rootfs_tar_sha256"] == payload["output_rootfs_tar_sha256"]
    assert not (fake_bin / "distros.txt").exists()


def test_build_official_managed_wsl2_runtime_rootfs_keep_build_distro_preserves_it(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    source = (
        programdata
        / "runtime"
        / "rootfs"
        / "sources"
        / "ubuntu-24.04-minimal-cloudimg-amd64-root.tar"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"base rootfs placeholder")
    fake_bin = tmp_path / "fake-bin"
    fake_wsl = _write_fake_official_rootfs_builder_wsl(fake_bin)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()

    _, payload = _run_official_rootfs_builder(
        programdata,
        "-SourceRootfsTarPath",
        str(source),
        "-ExpectedBaseRootfsSha256",
        sha,
        "-ConfirmBuild",
        "-KeepBuildDistro",
        env={"IMMOAPP_TEST_WSL_EXE": str(fake_wsl)},
    )

    assert payload["proof_result"] == "GO"
    assert payload["build_distro_cleanup_attempted"] is False
    assert payload["build_distro_cleanup_status"] == "kept"
    assert payload["build_distro_present_after_cleanup"] is True
    assert (fake_bin / "distros.txt").read_text(encoding="utf-8").strip() == ("ImmoAppRuntimeBuild")


def test_build_official_managed_wsl2_runtime_rootfs_failed_cleanup_is_visible(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    source = (
        programdata
        / "runtime"
        / "rootfs"
        / "sources"
        / "ubuntu-24.04-minimal-cloudimg-amd64-root.tar"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"base rootfs placeholder")
    fake_bin = tmp_path / "fake-bin"
    fake_wsl = _write_fake_official_rootfs_builder_wsl(fake_bin, fail_cleanup_unregister=True)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()

    result, payload = _run_official_rootfs_builder(
        programdata,
        "-SourceRootfsTarPath",
        str(source),
        "-ExpectedBaseRootfsSha256",
        sha,
        "-ConfirmBuild",
        env={"IMMOAPP_TEST_WSL_EXE": str(fake_wsl)},
        check=False,
    )

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == ("official_rootfs_build_distro_cleanup_failed_after_export")
    assert payload["output_rootfs_tar_sha256"]
    assert payload["import_plan_status"] == "GO"
    assert payload["build_distro_cleanup_attempted"] is True
    assert payload["build_distro_cleanup_status"] == "NO-GO"
    assert payload["build_distro_present_after_cleanup"] is True
    assert "simulated cleanup unregister failure" in payload["build_distro_cleanup_reason"]


def test_build_official_managed_wsl2_runtime_rootfs_has_log_policy_contract() -> None:
    script = _read("scripts/build_official_managed_wsl2_runtime_rootfs.ps1")

    assert "cloud-images.ubuntu.com/minimal/releases/noble/release/" in script
    assert "ubuntu-24.04-minimal-cloudimg-amd64-root.tar.xz" in script
    assert '"max-size": "10m"' in script
    assert '"max-file": "5"' in script
    assert "KeepBuildDistro" in script
    assert "build_distro_cleanup_status" in script
    assert "managed_wsl2_runtime_rootfs_inventory.json" in script
    assert "immoapp_managed_wsl2_runtime_rootfs_inventory" in script
    assert "rootfs_inventory_sha256" in script
    assert "apt_update()" in script
    assert "apt_install()" in script
    assert "--fix-missing" in script
    assert 'Acquire::http::Timeout "30";' in script
    assert "--unregister" in script
    assert "deployment\\managed-runtime" in script
    assert "official_rootfs_runtime_template_missing" in script
    assert "__IMMOAPP_RUNTIME_VERSION__" in script
    assert "opt/immoapp/runtime/bin/stop-managed-hub" in script
    assert "opt/immoapp/runtime/bin/restart-managed-hub" in script
    assert "opt/immoapp/runtime/compose/compose.yaml" in script
    assert "requiredRuntimeEntries" in script
    assert "-PlanOnly -ConfirmReplaceExistingDistro" in script
    assert "managed_wsl2_runtime_compose_payload_not_wired" not in script
    assert "managed_wsl2_runtime_logs_not_wired" not in script
    assert "log_policy_status" in script
    assert "runtime_start_status = $runtimeStartStatus" in script


def test_import_managed_wsl2_runtime_distro_requires_explicit_rootfs(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "logs" / "managed_wsl2_runtime_import_plan.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "import_managed_wsl2_runtime_distro.ps1"),
            "-PlanOnly",
            "-InstallLocation",
            str(programdata / "runtime" / "wsl" / "ImmoAppRuntime"),
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "managed_wsl2_rootfs_tar_path_required"
    assert payload["import_attempted"] is False
    assert payload["mutation_performed"] is False
    assert payload["runtime_start_status"] == "NO-GO"


def test_import_managed_wsl2_runtime_distro_rejects_missing_commands(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin, distro_name="")
    rootfs = tmp_path / "incomplete-rootfs.tar"
    _write_tar(rootfs, {"etc/os-release": b"ID=immoapp-test\n"})
    output = programdata / "logs" / "managed_wsl2_runtime_import_plan.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "import_managed_wsl2_runtime_distro.ps1"),
            "-RootfsTarPath",
            str(rootfs),
            "-InstallLocation",
            str(programdata / "runtime" / "wsl" / "ImmoAppRuntime"),
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "NO-GO"
    assert payload["rootfs_status"] == "NO-GO"
    assert payload["rootfs_missing_entries"] == list(MANAGED_WSL2_ROOTFS_REQUIRED_ENTRIES)
    assert payload["reason_code"] == "managed_wsl2_rootfs_required_command_missing"
    assert payload["import_attempted"] is False


def test_import_managed_wsl2_runtime_distro_plan_only_never_imports(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin, distro_name="")
    rootfs = tmp_path / "immoapp-runtime-rootfs.tar"
    _write_immoapp_rootfs_tar(rootfs)
    output = programdata / "logs" / "managed_wsl2_runtime_import_plan.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "import_managed_wsl2_runtime_distro.ps1"),
            "-RootfsTarPath",
            str(rootfs),
            "-InstallLocation",
            str(programdata / "runtime" / "wsl" / "ImmoAppRuntime"),
            "-OutputJson",
            str(output),
        ],
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["proof_result"] == "GO"
    assert payload["plan_only"] is True
    assert payload["import_status"] == "planned"
    assert payload["import_attempted"] is False
    assert payload["mutation_performed"] is False
    assert payload["runtime_start_status"] == "NO-GO"
    assert payload["agency_install_status"] == "NO_GO"


def test_import_managed_wsl2_runtime_distro_refuses_existing_without_replace(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    rootfs = tmp_path / "immoapp-runtime-rootfs.tar"
    _write_immoapp_rootfs_tar(rootfs)
    output = programdata / "logs" / "managed_wsl2_runtime_import_plan.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "import_managed_wsl2_runtime_distro.ps1"),
            "-RootfsTarPath",
            str(rootfs),
            "-InstallLocation",
            str(programdata / "runtime" / "wsl" / "ImmoAppRuntime"),
            "-OutputJson",
            str(output),
            "-ConfirmImportManagedWslRuntime",
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "NO-GO"
    assert payload["existing_distro_present"] is True
    assert payload["import_attempted"] is False
    assert payload["mutation_performed"] is False
    assert payload["reason_code"] == "managed_wsl2_runtime_distro_exists_replace_not_confirmed"


def test_import_managed_wsl2_runtime_updates_existing_payload_without_replacing_distro(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = fake_bin / "wsl-calls.log"
    wsl_py = fake_bin / "fake_wsl_update.py"
    wsl_py.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import pathlib, sys",
                f"calls = pathlib.Path({str(calls)!r})",
                "args = sys.argv[1:]",
                "calls.parent.mkdir(parents=True, exist_ok=True)",
                "with calls.open('a', encoding='utf-8') as fh:",
                "    fh.write(' '.join(args) + '\\n')",
                "if args[:2] == ['-l', '-q'] or args[:1] == ['-l']:",
                "    print('ImmoAppRuntime')",
                "    raise SystemExit(0)",
                "if args[:1] == ['--unregister'] or args[:1] == ['--import']:",
                "    raise SystemExit(42)",
                "if '-d' in args and 'sh' in args and '-lc' not in args:",
                "    print('managed_wsl2_runtime_was_running=true')",
                "    print('managed_wsl2_runtime_payload_update_go')",
                "    raise SystemExit(0)",
                "raise SystemExit(0)",
            ]
        ),
        encoding="utf-8",
    )
    (fake_bin / "wsl.cmd").write_text(
        "\n".join(
            [
                "@echo off",
                f'"{sys.executable}" "{wsl_py}" %*',
                "exit /b %ERRORLEVEL%",
            ]
        ),
        encoding="utf-8",
    )
    rootfs = tmp_path / "immoapp-runtime-rootfs.tar"
    _write_immoapp_rootfs_tar(rootfs)
    output = programdata / "logs" / "managed_wsl2_runtime_payload_update.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "import_managed_wsl2_runtime_distro.ps1"),
            "-RootfsTarPath",
            str(rootfs),
            "-OutputJson",
            str(output),
            "-UpdateExistingRuntimePayload",
            "-ConfirmUpdateExistingRuntimePayload",
        ],
        env=env,
    )

    payload = json.loads(result.stdout)
    call_text = calls.read_text(encoding="utf-8")
    assert payload["proof_result"] == "GO"
    assert payload["reason_code"] == "managed_wsl2_runtime_payload_updated"
    assert payload["existing_distro_present"] is True
    assert payload["payload_update_requested"] is True
    assert payload["payload_update_attempted"] is True
    assert payload["payload_update_status"] == "GO"
    assert payload["runtime_was_running"] is True
    assert payload["import_attempted"] is False
    assert payload["import_status"] == "not_attempted_existing_distro_payload_update"
    assert payload["mutation_performed"] is True
    assert "--unregister" not in call_text
    assert "--import" not in call_text
    assert "sh -lc" not in call_text
    assert "-- sh " in call_text
    importer = _read("scripts/import_managed_wsl2_runtime_distro.ps1")
    assert "./opt/immoapp/runtime" in importer
    assert "immoapp-runtime-update-tar.err" in importer
    assert "scriptTemplate = @'" in importer
    assert "__ROOTFS_QUOTED__" in importer
    assert "__REQUIRED_CHECKS__" in importer
    assert 'Replace("__REQUIRED_CHECKS__", $requiredChecks)' in importer
    assert "managed-wsl2-runtime-payload-update-{0}.sh" in importer
    assert "Test-ImmoAppPathHasReparsePoint -Path $tempScriptParent" in importer
    assert "WriteAllText($tempScriptPath" in importer
    assert "Convert-ImportRootfsHostPathToWslPath -Path $tempScriptPath" in importer
    assert "-d $DistroName -- sh $tempScriptWslPath" in importer
    assert 'staging="/opt/immoapp/runtime.update.$$"' in importer
    assert 'mkdir -p "$staging"' in importer
    assert "preserve_runtime_state" in importer
    assert "for item in secrets backups logs images state" in importer
    assert 'cp -a "$old_runtime/$item" "$new_runtime/$item"' in importer
    assert 'preserve_runtime_state "$previous" /opt/immoapp/runtime' in importer
    assert "payload-update-compose-ps.out" in importer
    assert "/opt/immoapp/runtime/bin/stop-managed-hub" in importer
    assert "managed_wsl2_runtime_was_running=" in importer
    assert 'status="$?"' in importer
    assert "rm -rf /opt/immoapp/runtime" in importer
    assert 'mv "$previous" /opt/immoapp/runtime' in importer
    assert payload["payload_update_rootfs_wsl_path"].startswith("/mnt/c/")


def test_import_managed_wsl2_runtime_accepts_verified_update_with_wsl_warning(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    wsl_py = fake_bin / "fake_wsl_warning_update.py"
    wsl_py.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import sys",
                "args = sys.argv[1:]",
                "if args[:2] == ['-l', '-q'] or args[:1] == ['-l']:",
                "    print('ImmoAppRuntime')",
                "    raise SystemExit(0)",
                "if '-d' in args and 'sh' in args and '-lc' not in args:",
                "    print('managed_wsl2_runtime_payload_update_go')",
                "    print(\"wsl: Failed to start the systemd user session for 'root'.\", file=sys.stderr)",
                "    raise SystemExit(1)",
                "raise SystemExit(0)",
            ]
        ),
        encoding="utf-8",
    )
    (fake_bin / "wsl.cmd").write_text(
        "\n".join(
            [
                "@echo off",
                f'"{sys.executable}" "{wsl_py}" %*',
                "exit /b %ERRORLEVEL%",
            ]
        ),
        encoding="utf-8",
    )
    rootfs = tmp_path / "immoapp-runtime-rootfs.tar"
    _write_immoapp_rootfs_tar(rootfs)
    output = programdata / "logs" / "managed_wsl2_runtime_payload_update.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
    }

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "import_managed_wsl2_runtime_distro.ps1"),
            "-RootfsTarPath",
            str(rootfs),
            "-OutputJson",
            str(output),
            "-UpdateExistingRuntimePayload",
            "-ConfirmUpdateExistingRuntimePayload",
        ],
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["proof_result"] == "GO"
    assert payload["reason_code"] == "managed_wsl2_runtime_payload_updated"
    assert payload["payload_update_status"] == "GO"
    assert "managed_wsl2_runtime_payload_update_go" in payload["payload_update_output"]
    assert "systemd user session" in payload["payload_update_output"]


def test_managed_runtime_log_retention_deletes_old_and_retains_recent(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    logs_root = programdata / "logs" / "managed-runtime"
    logs_root.mkdir(parents=True)
    old_log = logs_root / "old.log"
    recent_log = logs_root / "recent.log"
    old_log.write_text("old", encoding="utf-8")
    recent_log.write_text("recent", encoding="utf-8")
    _set_mtime_days_ago(old_log, 30)

    _, payload = _run_runtime_log_retention(programdata, retention_days=14)

    assert payload["proof_result"] == "GO"
    assert payload["retention_days"] == 14
    assert payload["max_total_bytes"] == 536870912
    assert payload["deleted_file_count"] == 1
    assert payload["failed_delete_count"] == 0
    assert payload["size_cap_satisfied"] is True
    assert payload["age_retention_satisfied"] is True
    assert payload["deleted_files"][0]["path"] == "old.log"
    assert not old_log.exists()
    assert recent_log.exists()
    assert payload["agency_install_status"] == "NO_GO"


def test_managed_runtime_log_retention_size_cap_deletes_oldest_first(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    logs_root = programdata / "logs" / "managed-runtime"
    logs_root.mkdir(parents=True)
    files = []
    for index, name in enumerate(("a.log", "b.log", "c.log")):
        path = logs_root / name
        path.write_bytes(bytes([index + 1]) * 80)
        _set_mtime_days_ago(path, 3 - index)
        files.append(path)

    _, payload = _run_runtime_log_retention(
        programdata,
        retention_days=365,
        max_total_bytes=160,
    )

    assert payload["proof_result"] == "GO"
    assert payload["deleted_file_count"] == 1
    assert payload["deleted_files"][0]["path"] == "a.log"
    assert payload["deleted_files"][0]["reason"] == "max_total_bytes_exceeded"
    assert payload["failed_delete_count"] == 0
    assert payload["size_cap_satisfied"] is True
    assert payload["age_retention_satisfied"] is True
    assert not files[0].exists()
    assert files[1].exists()
    assert files[2].exists()
    assert payload["retained_bytes"] <= 160


def test_managed_runtime_log_retention_is_idempotent(tmp_path: Path) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    logs_root = programdata / "logs" / "managed-runtime"
    logs_root.mkdir(parents=True)
    old_log = logs_root / "old.log"
    old_log.write_text("old", encoding="utf-8")
    _set_mtime_days_ago(old_log, 30)

    _, first = _run_runtime_log_retention(programdata)
    _, second = _run_runtime_log_retention(programdata)

    assert first["deleted_file_count"] == 1
    assert second["proof_result"] == "GO"
    assert second["deleted_file_count"] == 0
    assert second["deleted_bytes"] == 0
    assert second["failed_delete_count"] == 0
    assert second["size_cap_satisfied"] is True
    assert second["age_retention_satisfied"] is True


def test_managed_runtime_log_retention_locked_selected_log_is_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    logs_root = programdata / "logs" / "managed-runtime"
    logs_root.mkdir(parents=True)
    old_log = logs_root / "locked-old.log"
    old_log.write_bytes(b"x" * 80)
    _set_mtime_days_ago(old_log, 30)

    handle = _open_exclusive_windows_file_handle(old_log)
    try:
        result, payload = _run_runtime_log_retention(
            programdata,
            retention_days=14,
            max_total_bytes=1,
            check=False,
        )
    finally:
        _close_windows_file_handle(handle)

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "managed_runtime_log_retention_delete_incomplete"
    assert payload["deleted_file_count"] == 0
    assert payload["deleted_bytes"] == 0
    assert payload["failed_delete_count"] >= 1
    assert any(
        item["path"] == "locked-old.log" and "delete_failed" in item["reason"]
        for item in payload["failed_delete_files"]
    )
    assert payload["retained_bytes"] >= old_log.stat().st_size
    assert payload["size_cap_satisfied"] is False
    assert payload["age_retention_satisfied"] is False
    assert old_log.exists()

    _, retry = _run_runtime_log_retention(
        programdata,
        retention_days=14,
        max_total_bytes=1,
    )

    assert retry["proof_result"] == "GO"
    assert retry["deleted_file_count"] == 1
    assert retry["failed_delete_count"] == 0
    assert retry["retained_bytes"] == 0
    assert retry["size_cap_satisfied"] is True
    assert retry["age_retention_satisfied"] is True
    assert not old_log.exists()


def test_managed_runtime_log_retention_rejects_unsafe_root(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_log = outside / "old.log"
    outside_log.write_text("old", encoding="utf-8")
    _set_mtime_days_ago(outside_log, 30)

    result, payload = _run_runtime_log_retention(
        programdata,
        logs_root=outside,
        check=False,
    )

    assert result.returncode != 0
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "managed_runtime_log_retention_root_not_approved"
    assert outside_log.exists()


def test_managed_runtime_log_retention_does_not_follow_reparse_child(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    logs_root = programdata / "logs" / "managed-runtime"
    logs_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_log = outside / "old.log"
    outside_log.write_text("old", encoding="utf-8")
    _set_mtime_days_ago(outside_log, 30)
    link = logs_root / "linked"
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"New-Item -ItemType Junction -Path {_ps_quote(link)} -Target {_ps_quote(outside)}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    _, payload = _run_runtime_log_retention(programdata)

    assert outside_log.exists()
    assert payload["deleted_file_count"] == 0
    assert payload["skipped_file_count"] >= 1
    assert any(
        item["path"] == "linked" and item["reason"] == "reparse_point"
        for item in payload["skipped_reasons"]
    )


def test_managed_runtime_log_retention_never_deletes_adjacent_protected_files(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    protected = [
        programdata / "config" / "hub_runtime_provider.json",
        programdata / "config" / "hub_identity.json",
        programdata / "data" / "db" / "data.bin",
        programdata / "backups" / "backup.zip",
        programdata / "runtime" / "bin" / "runtime.exe",
        programdata / "logs" / "support_bundle.zip",
        programdata / "logs" / "installed_inventory.json",
    ]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"protected")
        _set_mtime_days_ago(path, 60)
    logs_root = programdata / "logs" / "managed-runtime"
    logs_root.mkdir(parents=True)
    old_log = logs_root / "old.log"
    old_log.write_text("old", encoding="utf-8")
    _set_mtime_days_ago(old_log, 60)

    _, payload = _run_runtime_log_retention(programdata)

    assert payload["deleted_file_count"] == 1
    assert not old_log.exists()
    for path in protected:
        assert path.exists(), f"protected file was deleted: {path}"


def test_hub_manager_cleanup_runtime_logs_calls_shared_helper() -> None:
    manager = _read("scripts/hub_manager.ps1")
    common = _read("scripts/common.ps1")
    assert '"cleanup-runtime-logs"' in manager
    assert "Invoke-ImmoAppManagedRuntimeLogRetention" in manager
    assert "function Invoke-ImmoAppManagedRuntimeLogRetention" in common


def test_hub_manager_installs_managed_wsl2_artifact_provider_and_detection(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    output = programdata / "logs" / "managed_wsl2_runtime_artifact_install.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)

    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata, output_json=output),
        env=env,
    )

    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    provider = json.loads(
        (programdata / "config" / "hub_runtime_provider.json").read_text(encoding="utf-8-sig")
    )
    detection = payload["runtime_detection"]
    assert payload["runtime_artifact_status"] == "GO"
    assert payload["existing_distro_present"] is True
    assert payload["runtime_payload_update_status"] == "GO"
    assert payload["runtime_payload_update_path"].endswith(
        "managed_wsl2_runtime_payload_update.json"
    )
    assert payload["runtime_start_status"] == "NO-GO"
    assert payload["proof_result"] == "NO-GO"
    assert payload["agency_install_status"] == "NO_GO"
    assert provider["provider_mode"] == "managed_wsl2_container_runtime_artifact"
    assert provider["runtime_dependency_mode"] == "managed_wsl2_container_runtime_artifact"
    assert provider["runtime_artifact_status"] == "GO"
    assert provider["runtime_start_status"] == "NO-GO"
    assert provider["image_bundle_archive_path"].endswith("immoapp-runtime-images.tar")
    assert provider["image_bundle_inventory_path"].endswith(
        "managed_wsl2_runtime_image_bundle_inventory.json"
    )
    assert provider["compose_payload_path"] == "/opt/immoapp/runtime/compose/compose.yaml"
    assert provider["compose_pull_policy"] == "never"
    assert provider["managed_backup_command_path"].endswith("backup-managed-hub.ps1")
    assert "web" in provider["required_compose_services"]
    assert "caddy" in provider["required_compose_services"]
    assert detection["runtime_dependency_mode"] == "managed_wsl2_container_runtime_artifact"
    assert detection["runtime_artifact_status"] == "GO"
    assert detection["runtime_start_status"] == "NO-GO"
    assert detection["provider_validation_status"] == "valid"
    assert detection["provider"]["managed_backup_command_path"].endswith("backup-managed-hub.ps1")
    assert detection["agency_install_status"] == "NO_GO"
    assert detection["reason_code"] == "managed_wsl2_runtime_start_not_proven"


def test_hub_manager_installs_managed_wsl2_artifact_imports_missing_distro(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin, distro_name="")
    output = programdata / "logs" / "managed_wsl2_runtime_artifact_install.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)

    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata, output_json=output),
        env=env,
    )

    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    import_payload = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_import_plan.json").read_text(
            encoding="utf-8-sig"
        )
    )

    assert payload["existing_distro_present"] is False
    assert payload["runtime_import_status"] == "GO"
    assert payload["runtime_import_path"].endswith("managed_wsl2_runtime_import_plan.json")
    assert import_payload["proof_result"] == "GO"
    assert import_payload["import_status"] == "GO"
    assert import_payload["import_attempted"] is True
    assert import_payload["mutation_performed"] is True
    assert payload["runtime_payload_update_status"] == "not_applicable"
    assert payload["runtime_artifact_status"] == "GO"
    assert payload["runtime_start_status"] == "NO-GO"


def test_detect_hub_runtime_rejects_stale_wsl_artifact_inventory_hash(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )
    inventory = programdata / "config" / "managed_wsl2_runtime_artifact_inventory.json"
    inventory.write_text(
        inventory.read_text(encoding="utf-8-sig").replace(
            "managed_wsl2_runtime_artifact_inventory",
            "managed_wsl2_runtime_artifact_inventory_modified",
        ),
        encoding="utf-8",
    )

    detected = json.loads(
        _run_powershell(
            ["-File", str(REPO_ROOT / "scripts" / "detect_hub_runtime.ps1")],
            env=env,
        ).stdout
    )

    assert detected["provider_validation_status"] == "invalid"
    assert detected["reason_code"] == "managed_wsl2_runtime_artifact_inventory_hash_mismatch"
    assert detected["agency_install_status"] == "NO_GO"


def test_hub_manager_start_refuses_wsl_artifact_without_start_bridge(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "start",
            "-HubBaseUrl",
            "http://127.0.0.1:9",
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "managed_wsl2_front_door_health_not_go" in (result.stderr + result.stdout)
    evidence = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_start_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert evidence["start_run_id"]
    assert evidence["runtime_command_status"] == "GO"
    assert evidence["front_door_health_status"] == "NO-GO"
    assert evidence["provider_config_sha256"]
    assert evidence["runtime_artifact_inventory_sha256"]
    assert evidence["managed_runtime_command_sha256"]


def test_hub_manager_start_with_wsl_artifact_requires_front_door_identity_for_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )
    server, front_door_url = _run_front_door_fixture()
    try:
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
                "-Action",
                "start",
                "-HubBaseUrl",
                front_door_url,
            ],
            env=env,
        )
        detected = json.loads(
            _run_powershell(
                ["-File", str(REPO_ROOT / "scripts" / "detect_hub_runtime.ps1")],
                env=env,
            ).stdout
        )
    finally:
        server.shutdown()
        server.server_close()

    evidence = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_start_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert evidence["proof_result"] == "GO"
    assert evidence["runtime_command_status"] == "GO"
    assert evidence["front_door_health_status"] == "GO"
    assert evidence["front_door_header"] == "caddy"
    assert evidence["identity_kind"] == "immoapp_hub_front_door_identity"
    assert evidence["start_run_id"]
    assert detected["runtime_start_status"] == "GO"
    assert detected["front_door_health_status"] == "GO"
    assert detected["reason_code"] == "managed_wsl2_runtime_internal_start_ready"
    assert detected["agency_install_status"] == "NO_GO"


def test_detect_hub_runtime_rejects_valid_wsl_artifact_start_evidence_when_front_door_down(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )
    server, front_door_url = _run_front_door_fixture()
    try:
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
                "-Action",
                "start",
                "-HubBaseUrl",
                front_door_url,
            ],
            env=env,
        )
    finally:
        server.shutdown()
        server.server_close()

    evidence = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_start_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert evidence["proof_result"] == "GO"
    detected = json.loads(
        _run_powershell(
            ["-File", str(REPO_ROOT / "scripts" / "detect_hub_runtime.ps1")],
            env=env,
        ).stdout
    )

    assert detected["runtime_artifact_status"] == "GO"
    assert detected["runtime_start_status"] == "NO-GO"
    assert detected["runtime_start_reason_code"] == "managed_wsl2_front_door_live_probe_failed"
    assert detected["front_door_health_status"] == "NO-GO"
    assert detected["front_door_live_probe"]["front_door_health_status"] == "NO-GO"
    assert detected["agency_install_status"] == "NO_GO"


def test_hub_manager_start_with_wsl_artifact_missing_distro_reports_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin, distro_name="OtherRuntime")
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )

    result = _run_powershell(
        ["-File", str(REPO_ROOT / "scripts" / "hub_manager.ps1"), "-Action", "start"],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "managed_wsl2_runtime_distribution_missing" in (result.stderr + result.stdout)
    evidence = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_start_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert evidence["runtime_identity_status"] == "NO-GO"
    assert evidence["container_engine_status"] == "NO-GO"
    assert evidence["compose_status"] == "NO-GO"
    assert evidence["proof_result"] == "NO-GO"


def test_hub_manager_start_with_wsl_artifact_identity_mismatch_reports_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin, identity_distro_name="OtherRuntime")
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )

    result = _run_powershell(
        ["-File", str(REPO_ROOT / "scripts" / "hub_manager.ps1"), "-Action", "start"],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "managed_wsl2_runtime_identity_mismatch" in (result.stderr + result.stdout)
    bootstrap = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_bootstrap_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert bootstrap["expected_distro_name"] == "ImmoAppRuntime"
    assert bootstrap["actual_distro_name"] == "OtherRuntime"
    assert bootstrap["runtime_identity_status"] == "NO-GO"


def test_hub_manager_start_with_compose_cli_but_daemon_down_is_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(
        fake_bin,
        container_engine_status="NO-GO",
        compose_status="GO",
        docker_daemon_status="NO-GO",
        docker_info_status="NO-GO",
        reason_code="managed_wsl2_container_engine_not_go",
    )
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )

    result = _run_powershell(
        ["-File", str(REPO_ROOT / "scripts" / "hub_manager.ps1"), "-Action", "start"],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "managed_wsl2_container_engine_not_go" in (result.stderr + result.stdout)
    evidence = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_start_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert evidence["runtime_command_status"] == "NO-GO"
    assert evidence["container_engine_status"] == "NO-GO"
    assert evidence["compose_cli_status"] == "GO"
    assert evidence["compose_status"] == "GO"
    assert evidence["docker_daemon_status"] == "NO-GO"
    assert evidence["proof_result"] == "NO-GO"


def test_hub_manager_start_with_wsl_bridge_hang_times_out_and_writes_evidence(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin, hang_service_command=True)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_MANAGED_WSL2_BRIDGE_TIMEOUT_SECONDS": "6",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )

    result = _run_powershell(
        ["-File", str(REPO_ROOT / "scripts" / "hub_manager.ps1"), "-Action", "start"],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "managed_wsl2_runtime_bridge_timeout" in (result.stderr + result.stdout)
    evidence = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_start_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert evidence["runtime_command_status"] == "NO-GO"
    assert evidence["runtime_bridge_timed_out"] is True
    assert evidence["runtime_bridge_timeout_seconds"] == 6
    assert evidence["reason_code"] == "managed_wsl2_runtime_bridge_timeout"
    assert evidence["proof_result"] == "NO-GO"


def test_hub_manager_start_with_wsl_artifact_partial_service_status_is_no_go(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin, service_status="NO-GO")
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )
    server, front_door_url = _run_front_door_fixture()
    try:
        result = _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
                "-Action",
                "start",
                "-HubBaseUrl",
                front_door_url,
            ],
            env=env,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode != 0
    assert "hub_backend_services_unhealthy_or_timeout" in (result.stderr + result.stdout)
    evidence = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_start_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert evidence["service_status"] == "NO-GO"
    assert evidence["runtime_compose_service_status"] == "NO-GO"
    assert evidence["front_door_health_status"] == "GO"
    assert evidence["proof_result"] == "NO-GO"


def test_hub_manager_start_with_wsl_artifact_preexisting_backend_port_is_contaminated(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )
    backend_server = ThreadingHTTPServer(("127.0.0.1", 0), _FrontDoorHandler)
    env["IMMOAPP_TEST_PRESTART_BACKEND_URL"] = (
        f"http://127.0.0.1:{backend_server.server_address[1]}/api/v1/health/"
    )
    thread = threading.Thread(target=backend_server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_powershell(
            ["-File", str(REPO_ROOT / "scripts" / "hub_manager.ps1"), "-Action", "start"],
            env=env,
            check=False,
        )
    finally:
        backend_server.shutdown()
        backend_server.server_close()

    assert result.returncode != 0
    assert "managed_wsl2_pre_start_port_contamination" in (result.stderr + result.stdout)
    evidence = json.loads(
        (programdata / "logs" / "managed_wsl2_runtime_start_evidence.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert evidence["pre_start_backend_direct_reachable"] is True
    assert evidence["runtime_command_status"] == "NO-GO"
    assert evidence["proof_result"] == "NO-GO"


def test_detect_hub_runtime_rejects_stale_wsl_artifact_start_evidence(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )
    server, front_door_url = _run_front_door_fixture()
    try:
        _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
                "-Action",
                "start",
                "-HubBaseUrl",
                front_door_url,
            ],
            env=env,
        )
    finally:
        server.shutdown()
        server.server_close()

    provider = programdata / "config" / "hub_runtime_provider.json"
    provider_payload = json.loads(provider.read_text(encoding="utf-8-sig"))
    provider_payload["created_at_utc"] = "2026-02-02T00:00:00Z"
    provider.write_text(json.dumps(provider_payload), encoding="utf-8")
    detected = json.loads(
        _run_powershell(
            ["-File", str(REPO_ROOT / "scripts" / "detect_hub_runtime.ps1")],
            env=env,
        ).stdout
    )

    assert detected["runtime_artifact_status"] == "GO"
    assert detected["runtime_start_status"] == "NO-GO"
    assert detected["runtime_start_reason_code"] == "managed_wsl2_runtime_start_evidence_invalid"
    assert detected["agency_install_status"] == "NO_GO"


def test_hub_manager_start_with_missing_wsl_artifact_wrapper_does_not_fallback(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "IMMOAPP_TEST_PRESTART_FRONT_DOOR_URL": "http://127.0.0.1:9/api/v1/health/",
        "IMMOAPP_TEST_PRESTART_BACKEND_URL": "http://127.0.0.1:9/api/v1/health/",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    env = _write_fake_packaged_managed_wsl2_payload(tmp_path, programdata, env)
    _run_powershell(
        _hub_manager_install_runtime_artifact_args(programdata),
        env=env,
    )
    (programdata / "runtime" / "managed-wsl2-artifact" / "bin" / "start-managed-hub.ps1").unlink()

    result = _run_powershell(
        ["-File", str(REPO_ROOT / "scripts" / "hub_manager.ps1"), "-Action", "start"],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    combined = result.stderr + result.stdout
    assert "managed_runtime_provider_invalid" in combined
    assert "stack.ps1" not in combined


def test_hub_manager_remove_runtime_candidate_restores_fallback_detection(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    install_owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "install-runtime-candidate",
    )
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "install-runtime-candidate",
            "-ConfirmInstallRuntimeCandidate",
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "8",
            *install_owner_evidence_args,
            "-OutputJson",
            str(programdata / "logs" / "candidate.json"),
        ],
        env=env,
    )
    provider = programdata / "config" / "hub_runtime_provider.json"
    assert provider.exists()

    output = programdata / "logs" / "removed.json"
    remove_owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "remove-runtime-candidate",
    )
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "remove-runtime-candidate",
            *remove_owner_evidence_args,
            "-OutputJson",
            str(output),
        ],
        env=env,
    )

    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "GO"
    assert payload["removed_provider_config"] is True
    assert payload["removed_runtime_data"] is False
    assert payload["removed_hub_identity"] is False
    assert not provider.exists()
    assert (
        payload["runtime_detection_after_removal"]["runtime_dependency_mode"]
        != "managed_wsl2_container_runtime_candidate"
    )


def test_hub_manager_remove_runtime_candidate_is_idempotent_when_missing(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "logs" / "removed.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "remove-runtime-candidate",
    )

    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "remove-runtime-candidate",
            *owner_evidence_args,
            "-OutputJson",
            str(output),
        ],
        env=env,
    )

    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["proof_result"] == "GO"
    assert payload["provider_was_present"] is False
    assert payload["removed_provider_config"] is False
    assert (
        payload["runtime_detection_after_removal"]["runtime_dependency_mode"]
        != "managed_wsl2_container_runtime_candidate"
    )


def test_hub_manager_remove_runtime_candidate_refuses_non_candidate_provider(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    config = programdata / "config"
    config.mkdir(parents=True)
    provider = config / "hub_runtime_provider.json"
    provider_payload = {
        "kind": "immoapp_hub_runtime_provider",
        "schema_version": 1,
        "provider_mode": "managed_container_runtime",
        "runtime_dependency_mode": "managed_container_runtime",
        "proof_only": False,
    }
    provider.write_text(json.dumps(provider_payload, sort_keys=True), encoding="utf-8")
    original_bytes = provider.read_bytes()
    output = programdata / "logs" / "removed.json"
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "remove-runtime-candidate",
    )

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "remove-runtime-candidate",
            *owner_evidence_args,
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "managed_runtime_provider_not_wsl_candidate" in (result.stderr + result.stdout)
    assert provider.read_bytes() == original_bytes


def test_detect_hub_runtime_rejects_wsl_policy_config_plan_semantic_mismatch(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "install-runtime-candidate",
    )
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "hub_manager.ps1"),
            "-Action",
            "install-runtime-candidate",
            "-ConfirmInstallRuntimeCandidate",
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "8",
            *owner_evidence_args,
            "-OutputJson",
            str(programdata / "logs" / "candidate.json"),
        ],
        env=env,
    )
    provider_path = programdata / "config" / "hub_runtime_provider.json"
    provider = json.loads(provider_path.read_text(encoding="utf-8-sig"))
    config_plan_path = Path(provider["wsl_config_plan_json_path"])
    config_plan = json.loads(config_plan_path.read_text(encoding="utf-8-sig"))
    config_plan["policy_json"]["planned_wsl_processors"] = 2
    config_plan_path.write_text(json.dumps(config_plan), encoding="utf-8")
    provider["wsl_config_plan_sha256"] = hashlib.sha256(config_plan_path.read_bytes()).hexdigest()
    provider_path.write_text(json.dumps(provider), encoding="utf-8")

    result = _run_powershell(
        ["-File", str(REPO_ROOT / "scripts" / "detect_hub_runtime.ps1")],
        env=env,
        check=False,
    )
    data = json.loads(result.stdout)
    assert data["provider_config_valid"] is False
    assert data["provider_validation_status"] == "invalid"
    assert data["reason_code"] == "wsl_config_plan_policy_mismatch"


def test_setup_office_hub_can_record_requested_wsl_candidate_state(tmp_path: Path) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "logs" / "hub-foundation.json"
    fake_bin = tmp_path / "bin"
    _write_fake_wsl_command(fake_bin)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_WSL_EXE": str(fake_bin / "wsl.cmd"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "USERPROFILE": str(tmp_path / "profile"),
    }
    (tmp_path / "profile").mkdir()
    owner_evidence_args = _hub_manager_owner_evidence_args(
        programdata,
        env,
        "install-runtime-candidate",
    )

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "setup_office_hub.ps1"),
            "-Role",
            "HubDesktop",
            "-HubDisplayName",
            "Main Office",
            "-DataRoot",
            str(programdata),
            "-NoLanAccess",
            "-NoAutoStart",
            "-NoStartHub",
            "-NoShortcuts",
            "-ConfigureWslRuntimeCandidate",
            "-MachineTotalMemoryGb",
            "16",
            "-MachineLogicalProcessors",
            "8",
            *owner_evidence_args,
            "-OutputJson",
            str(output),
        ],
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["wsl_runtime_candidate_requested"] is True
    assert payload["candidate_registration_status"] == "GO"
    assert payload["runtime_artifact_status"] == "NO-GO"
    assert payload["runtime_start_status"] == "NO-GO"
    assert payload["wsl_runtime_candidate_install"]["candidate_registration_status"] == "GO"
    assert payload["runtime_detection"]["runtime_dependency_mode"] == (
        "managed_wsl2_container_runtime_candidate"
    )
    assert payload["runtime_detection"]["agency_install_status"] == "NO_GO"
    assert "managed_runtime_not_agency_ready" in payload["no_go_reasons"]


def test_hub_script_source_resolution_distinguishes_repo_and_installed_app(
    tmp_path: Path,
) -> None:
    repo_script = (
        f". '{REPO_ROOT / 'scripts' / 'common.ps1'}'; "
        "$manager = Resolve-ImmoAppHubManagerScript; "
        "$desktop = Resolve-ImmoAppDesktopExecutable; "
        "[ordered]@{ root_source = Get-ImmoAppCurrentScriptRootSource; "
        "manager_source = $manager.source; desktop_source = $desktop.source } | ConvertTo-Json -Depth 4"
    )
    repo_result = _run_powershell(["-Command", repo_script])
    repo_payload = json.loads(repo_result.stdout)
    assert repo_payload["root_source"] == "repo_dev"
    assert repo_payload["manager_source"] == "repo_dev"
    assert repo_payload["desktop_source"] in {"repo_dev", "missing"}

    app_root = tmp_path / "Programs" / "ImmoApp Beta"
    scripts_root = app_root / "scripts"
    scripts_root.mkdir(parents=True)
    (app_root / "ImmoApp.exe").write_text("fake exe", encoding="utf-8")
    identity_root = app_root / "_internal" / "app"
    identity_root.mkdir(parents=True)
    (identity_root / "installer_build_identity.json").write_text(
        '{"kind":"immoapp_installer_build_identity"}',
        encoding="utf-8",
    )
    shutil.copy2(REPO_ROOT / "scripts" / "common.ps1", scripts_root / "common.ps1")
    shutil.copy2(REPO_ROOT / "scripts" / "hub_manager.ps1", scripts_root / "hub_manager.ps1")

    installed_script = (
        f". '{scripts_root / 'common.ps1'}'; "
        "$manager = Resolve-ImmoAppHubManagerScript; "
        "$desktop = Resolve-ImmoAppDesktopExecutable; "
        "[ordered]@{ root_source = Get-ImmoAppCurrentScriptRootSource; "
        "manager_source = $manager.source; desktop_source = $desktop.source; "
        "manager_path = $manager.path; desktop_path = $desktop.path } | ConvertTo-Json -Depth 4"
    )
    installed_result = _run_powershell(["-Command", installed_script])
    installed_payload = json.loads(installed_result.stdout)
    assert installed_payload["root_source"] == "installed_app"
    assert installed_payload["manager_source"] == "installed_app"
    assert installed_payload["desktop_source"] == "installed_app"
    assert Path(installed_payload["manager_path"]) == scripts_root / "hub_manager.ps1"
    assert Path(installed_payload["desktop_path"]) == app_root / "ImmoApp.exe"

    programdata = tmp_path / "ProgramData" / "ImmoApp"
    programdata_scripts = programdata / "app" / "scripts"
    programdata_scripts.mkdir(parents=True)
    (programdata / "app" / "ImmoApp.exe").write_text("fake exe", encoding="utf-8")
    shutil.copy2(REPO_ROOT / "scripts" / "common.ps1", programdata_scripts / "common.ps1")
    shutil.copy2(REPO_ROOT / "scripts" / "hub_manager.ps1", programdata_scripts / "hub_manager.ps1")
    programdata_script = (
        f". '{programdata_scripts / 'common.ps1'}'; "
        "$manager = Resolve-ImmoAppHubManagerScript; "
        "$desktop = Resolve-ImmoAppDesktopExecutable; "
        "[ordered]@{ root_source = Get-ImmoAppCurrentScriptRootSource; "
        "manager_source = $manager.source; desktop_source = $desktop.source } | ConvertTo-Json -Depth 4"
    )
    programdata_result = _run_powershell(
        ["-Command", programdata_script],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )
    programdata_payload = json.loads(programdata_result.stdout)
    assert programdata_payload["root_source"] == "installed_programdata"
    assert programdata_payload["manager_source"] == "installed_programdata"
    assert programdata_payload["desktop_source"] == "installed_programdata"


def test_hub_identity_scripts_validate_display_name_and_do_not_mutate_hostname(
    tmp_path: Path,
) -> None:
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(tmp_path / "ProgramData" / "ImmoApp"),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "set_hub_identity.ps1"),
            "-HubDisplayName",
            "Main Office",
        ],
        env=env,
    )
    payload = json.loads(result.stdout)
    assert payload["proof_result"] == "GO"
    assert payload["hub_identity"]["hub_display_name"] == "Main Office"
    assert payload["hostname_mutated"] is False

    for rejected in ("http://hub.local", "127.0.0.1", "localhost", "DESKTOP-ABC123"):
        failed = _run_powershell(
            [
                "-File",
                str(REPO_ROOT / "scripts" / "set_hub_identity.ps1"),
                "-HubDisplayName",
                rejected,
            ],
            env=env,
            check=False,
        )
        assert failed.returncode != 0
        assert "Choose a simple name your team will recognize" in (failed.stderr + failed.stdout)

    common = _read("scripts/common.ps1")
    setup = _read("scripts/setup_office_hub.ps1")
    identity_scripts = _read("scripts/set_hub_identity.ps1") + _read("scripts/get_hub_identity.ps1")
    forbidden = ("Rename-Computer", "Set-ComputerName", "Win32_ComputerSystem")
    for token in forbidden:
        assert token not in common
        assert token not in setup
        assert token not in identity_scripts


def test_setup_office_hub_validate_only_is_plan_not_applied_proof(tmp_path: Path) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "logs" / "hub-foundation.json"
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "setup_office_hub.ps1"),
            "-Role",
            "HubDesktop",
            "-HubDisplayName",
            "Main Office",
            "-DataRoot",
            str(programdata),
            "-ValidateOnly",
            "-CreateFirewallRule",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )
    assert "Proof result: NO-GO" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["kind"] == "immoapp_hub_installer_foundation_evidence"
    assert payload["setup_result_kind"] == "immoapp_hub_setup_result"
    assert payload["validate_only"] is True
    assert payload["selected_role"] == "hub_desktop"
    assert payload["hub_identity_status"] == "GO"
    assert payload["hub_identity_written"] is False
    assert payload["hub_identity"]["hub_identity"]["source"] == "installer_setup"
    assert payload["hub_identity"]["hostname_mutated"] is False
    assert payload["directories_status"] == "GO"
    assert {entry["name"] for entry in payload["directories"]["directories"]} == {
        "config",
        "data",
        "logs",
        "runtime",
    }
    assert payload["front_door_status"] == "GO"
    assert payload["front_door_service"] == "caddy"
    assert payload["firewall_status"] == "intended"
    assert payload["foundation_plan_status"] == "GO"
    assert payload["foundation_applied_status"] == "NOT_APPLICABLE"
    assert payload["hub_foundation_status"] == "NOT_APPLICABLE"
    assert payload["proof_result"] == "NO-GO"
    assert payload["dry_run_reason"] == "validate_only_is_planning_evidence_not_applied_setup_proof"
    assert payload["agency_install_status"] == "NO_GO"
    assert payload["public_beta_status"] == "NO_GO"
    assert "managed_runtime_not_agency_ready" in payload["no_go_reasons"]


def test_setup_office_hub_applied_local_only_foundation_requires_real_writes(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "logs" / "hub-foundation.json"
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "setup_office_hub.ps1"),
            "-Role",
            "HubDesktop",
            "-HubDisplayName",
            "Main Office",
            "-DataRoot",
            str(programdata),
            "-NoLanAccess",
            "-NoAutoStart",
            "-NoStartHub",
            "-NoShortcuts",
            "-SetupRunId",
            "applied-local-test-run",
            "-SelectedInstallDesktop",
            "false",
            "-SelectedInstallHub",
            "true",
            "-InstallMode",
            "hub_only",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            "IMMOAPP_HUB_FRONT_DOOR_PORT": "8000",
        },
    )
    assert "Proof result: GO" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["setup_run_id"] == "applied-local-test-run"
    assert payload["selected_install_desktop"] is False
    assert payload["selected_install_hub"] is True
    assert payload["install_mode"] == "hub_only"
    assert payload["validate_only"] is False
    assert payload["foundation_plan_status"] == "GO"
    assert payload["foundation_applied_status"] == "GO"
    assert payload["hub_foundation_status"] == "GO"
    assert payload["proof_result"] == "GO"
    assert payload["hub_identity_written"] is True
    assert Path(payload["hub_identity_path"]).exists()
    assert payload["lan_access_enabled"] is False
    assert payload["firewall_status"] == "skipped_local_only"
    assert payload["front_door_url"] == "http://127.0.0.1:8000"
    assert payload["runtime_hidden_from_operator"] is False
    assert payload["docker_compose_hidden_from_user"] is False
    assert payload["agency_install_status"] == "NO_GO"
    assert "desktop_not_installed_path" not in payload["no_go_reasons"]


def test_setup_office_hub_lan_foundation_rejects_skipped_firewall(tmp_path: Path) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    output = programdata / "logs" / "hub-foundation.json"
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "setup_office_hub.ps1"),
            "-Role",
            "HubDesktop",
            "-HubDisplayName",
            "Main Office",
            "-DataRoot",
            str(programdata),
            "-NoAutoStart",
            "-NoStartHub",
            "-NoShortcuts",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )
    assert "Proof result: NO-GO" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8-sig"))
    assert payload["lan_access_enabled"] is True
    assert payload["firewall_status"] == "skipped_no_lan_requested"
    assert payload["foundation_applied_status"] == "NO-GO"
    assert "firewall_rule_not_applied_or_invalid_for_lan" in payload["foundation_no_go_reasons"]


def test_managed_wsl_portproxy_evidence_accepts_existing_valid_rule(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    text = "\n".join(
        [
            "Listen on ipv4:             Connect to ipv4:",
            "",
            "Address         Port        Address         Port",
            "--------------- ----------  --------------- ----------",
            "192.168.1.20    8000        172.30.10.2     8000",
        ]
    )
    result = _run_powershell(
        [
            "-Command",
            (
                ". .\\scripts\\common.ps1; "
                "$e = Ensure-ImmoAppHubWslPortProxy "
                "-LanAccess -Requested -ListenAddress '192.168.1.20' -Port 8000; "
                "$e | ConvertTo-Json -Depth 6"
            ),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            "IMMOAPP_TEST_MANAGED_WSL_IP": "172.30.10.2",
            "IMMOAPP_TEST_PORTPROXY_TEXT": text,
            "IMMOAPP_TEST_IS_ADMIN": "false",
        },
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "already_present_valid"
    assert payload["verified"] is True
    assert payload["listen_address"] == "192.168.1.20"
    assert payload["listen_port"] == 8000
    assert payload["connect_address"] == "172.30.10.2"
    assert payload["connect_port"] == 8000


def test_managed_wsl_portproxy_requires_admin_when_rule_missing(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    result = _run_powershell(
        [
            "-Command",
            (
                ". .\\scripts\\common.ps1; "
                "$e = Ensure-ImmoAppHubWslPortProxy "
                "-LanAccess -Requested -ListenAddress '192.168.1.20' -Port 8000; "
                "$e | ConvertTo-Json -Depth 6"
            ),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            "IMMOAPP_TEST_MANAGED_WSL_IP": "172.30.10.2",
            "IMMOAPP_TEST_PORTPROXY_TEXT": "Address Port Address Port",
            "IMMOAPP_TEST_IS_ADMIN": "false",
        },
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "needs_admin"
    assert payload["verified"] is False
    assert payload["reason_code"] == "portproxy_rule_needs_admin"


def test_managed_wsl_start_evidence_requires_portproxy_only_for_explicit_lan_url() -> None:
    collector = _read("scripts/collect_managed_wsl2_runtime_start_evidence.ps1")
    assert "$identityBridgeTimeoutSeconds = 120" in collector
    assert (
        '$frontDoorProofRequired = ($Action -in @("start", "restart", "status", "health"))'
        in collector
    )
    assert "if (-not $frontDoorProofRequired)" in collector
    assert "$explicitFrontDoorUrl = -not [string]::IsNullOrWhiteSpace($HubBaseUrl)" in collector
    assert '"http://127.0.0.1:$(Get-ImmoAppHubPort)"' in collector
    assert "if ($explicitFrontDoorUrl -and (-not $frontDoorIsLoopback)" in collector
    assert (
        '$serviceProofRequired = ($Action -in @("start", "restart", "status", "health", "backup"))'
        in collector
    )
    assert '$serviceOk = ((-not $serviceProofRequired) -or $serviceStatus -eq "GO")' in collector
    assert "service_proof_required" in collector
    assert "Ensure-ImmoAppHubWslPortProxy" in collector
    assert "wsl_portproxy_status" in collector
    assert "wsl_portproxy_verified" in collector
    assert "managed_wsl2_portproxy_not_verified" in collector
    assert "explicit_front_door_url_requested" in collector
    assert 'wsl_portproxy = if ($networkBridgeOk) { "GO" } else { "NO-GO" }' in collector


def test_hub_evidence_scripts_use_required_common_envelope_and_no_fake_go() -> None:
    install = _read("scripts/collect_hub_install_evidence.ps1")
    status = _read("scripts/collect_hub_status_evidence.ps1")
    detect = _read("scripts/detect_hub_runtime.ps1")
    common = _read("scripts/common.ps1")
    for text, kind in (
        (install, "immoapp_hub_install_evidence"),
        (status, "immoapp_hub_status_evidence"),
    ):
        assert f'kind = "{kind}"' in text
        for field in (
            "schema_version",
            "created_at_utc",
            "machine_name",
            "windows_user",
            "source_commit_sha",
            "installer_sha256",
            "installed_version",
            "installed_build_identity",
            "proof_result",
            "failure_reason",
        ):
            assert field in text
    assert 'kind = "immoapp_hub_runtime_detection"' in detect
    assert "detect_hub_runtime.ps1" in install
    assert "runtime_detection = $runtimeDetection" in install
    assert "Manual Docker Desktop/runtime use is internal-beta only" in install
    assert "provider_validation_status" in install
    assert "hub_manager_script_source" in install
    assert "desktop_exe_source" in install
    assert "Test-ImmoAppInstalledSource -Source" in install
    assert "real agency install requires installed source" in install
    assert '[string]$hubManagerScript.source -ne "installed"' not in install
    assert '[string]$desktopExe.source -ne "installed"' not in install
    assert "Test-ManagedWsl2ArtifactRuntimeReady" in status
    assert "Import-ManagedWsl2StartEvidence" in status
    assert "Get-ManagedWsl2ArtifactServiceStatus" in status
    assert "available_internal_wsl2_artifact_no_go" in status
    assert "managed_runtime_start_evidence_status" in status
    assert "hub_identity_status = [string]$hubState.hub_identity_status" in status
    assert "hub_state_manifest_status = [string]$hubState.hub_state_manifest_status" in status
    assert "front_door_url = $hubUrl" in status
    for field in (
        "runtime_dependency_mode",
        "docker_cli_available",
        "docker_engine_reachable",
        "docker_desktop_detected",
        "compose_available",
        "runtime_is_user_visible",
        "agency_install_status",
        "reason_code",
        "recommended_next_action",
        "provider_config_valid",
        "provider_config_error",
        "provider_validation_status",
    ):
        assert field in detect
    for field in (
        "immoapp_hub_runtime_provider",
        "provider_mode",
        "installed_by_immoapp",
        "user_visible_runtime",
        "runtime_executable_path",
        "compose_mode",
        "install_root",
        "data_root",
        "logs_root",
    ):
        assert field in detect
    assert '"manual_docker_desktop"' in detect
    assert '"managed_container_runtime"' in detect
    assert '"native_windows_services"' in detect
    assert '"unavailable"' in detect
    assert '"invalid_provider_config"' in detect
    assert '"NO_GO"' in detect
    assert "Get-ImmoAppHubRequiredComposeServices" in common
    assert "Invoke-ImmoAppHubCompose" in common
    assert "Get-ImmoAppHubComposeInvocation" in common
    assert "runtime_profile" in status
    assert "runtime_detection = $runtimeDetection" in status
    assert "failing_services = $failingServices" in status
    assert "missing_services = $missingServices" in status
    assert "starting_services = $startingServices" in status
    assert "runtime_state = $runtimeState" in status
    assert "compose_state = $composeState" in status
    assert "status_reason_code = $statusReasonCode" in status
    assert "Get-FailingComposeServices" in status
    assert "Resolve-ComposeState" in status
    assert "stack_stopped" in status
    assert "partial_stack_required_services_missing" in status
    assert "service_missing" in status
    assert "health_endpoint_unreachable" in status
    assert "runtime_unavailable" in status
    assert "windows_firewall_rule_status" in status
    assert "backup_status" in status
    for token in (
        "runtime_hidden_from_operator",
        "docker_desktop_detected",
        "manual_docker_desktop_internal_only",
    ):
        assert token in install
        assert token in status
    assert "docker_compose_hidden_from_user = $true" not in install
    assert "docker_compose_hidden_from_user = $true" not in status
    assert "runtime_provider_proof" in install
    assert "provider_validation_status" in status


def test_hub_m1_go_no_go_aggregator_requires_all_proof_tracks() -> None:
    verifier = _read("scripts/verify_hub_beta_m1_evidence.ps1")
    assert "immoapp_hub_beta_m1_go_no_go_evidence" in verifier
    for token in (
        "HubInstallEvidenceJson",
        "HubStatusEvidenceJson",
        "WorkstationReachabilityJson",
        "WorkstationProductProofJson",
        "BackupRestoreProofJson",
        "SupportBundleManifestJson",
        "SupportBundlePath",
        "InstalledInventoryJson",
        "InstallLifecycleEvidenceJson",
        "managed_container_runtime",
        "Test-CanonicalProviderConfigPath",
        "immoapp_lan_workstation_reachability_proof",
        "immoapp_manual_product_proof_evidence",
    ):
        assert token in verifier
    assert "Test-LocalhostUrl" in verifier
    assert "Test-SyntheticEvidence" in verifier
    assert "local_hub_only" in verifier
    assert "provider_validation_status" in verifier
    assert "managed_runtime_ready" in verifier
    assert "hub_manager_script_source" in verifier
    assert "desktop_exe_source" in verifier
    assert "Test-ImmoAppInstalledSource" in verifier
    assert "installed_app" in _read("scripts/common.ps1")
    assert "installed_programdata" in _read("scripts/common.ps1")
    assert "proof_result" in verifier
    assert "exit 1" in verifier


def test_hub_local_proof_runner_is_local_only_and_uses_existing_tools() -> None:
    proof = _read("scripts/verify_hub_m1_local_proof.ps1")
    assert "[switch]$ValidateOnly" in proof
    assert "[switch]$StartHubForProof" in proof
    assert "ValidateOnly and StartHubForProof are mutually exclusive" in proof
    assert "detect_hub_runtime.ps1" in proof
    assert "setup_office_hub.ps1" in proof
    assert '"-Role", "HubDesktop"' in proof
    assert "-ValidateOnly" in proof
    assert "-StartHub" in proof
    assert "collect_hub_status_evidence.ps1" in proof
    assert "collect_hub_install_evidence.ps1" in proof
    assert "verify_hub_network_boundary.ps1" in proof
    assert "collect_desktop_support_bundle.ps1" in proof
    assert "backup_release_bundle.ps1" in proof
    assert "verify_hub_beta_m1_evidence.ps1" in proof
    assert 'proof_scope = "local_only"' in proof
    assert "synthetic = $true" in proof
    assert "runtime_provider_proof" in proof
    assert "internal_hub_status" in proof
    assert "observed_existing_hub_status" in proof
    assert "started_hub_status" in proof
    assert "startup_attempted" in proof
    assert "not_applicable" in proof
    assert "agency_install_status" in proof
    assert "backup_restore_status" in proof
    assert "missing_restore_evidence" in proof
    assert "source_bucket_used_as_restore_target" in proof
    assert "real_agency_install_status" in proof
    assert "Remove-Item" not in proof


def test_lan_web_binding_is_role_aware_and_infra_ports_stay_private() -> None:
    compose = _read("deployment/compose/compose.yml")
    env = _read("deployment/env/.env.example")
    common = _read("scripts/common.ps1")

    assert (
        '"${IMMOAPP_WEB_BIND_HOST:-127.0.0.1}:${IMMOAPP_BACKEND_HOST_PORT:-8000}:8000"' in compose
    )
    for private_port in (
        '"127.0.0.1:5432:5432"',
        '"127.0.0.1:5672:5672"',
        '"127.0.0.1:6379:6379"',
        '"127.0.0.1:8200:8200"',
        '"127.0.0.1:9000:9000"',
        '"127.0.0.1:9001:9001"',
        '"127.0.0.1:3310:3310"',
    ):
        assert private_port in compose
    assert "0.0.0.0:5432" not in compose
    assert "0.0.0.0:9000" not in compose
    assert "0.0.0.0:9001" not in compose
    assert 'profiles: ["hub-front-door"]' in compose
    assert (
        '"${IMMOAPP_CADDY_BIND_HOST:-127.0.0.1}:${IMMOAPP_HUB_FRONT_DOOR_PORT:-8000}:8000"'
        in compose
    )
    assert '"80:80"' not in compose
    assert '"443:443"' not in compose
    assert "IMMOAPP_WEB_BIND_HOST=127.0.0.1" in env
    assert "IMMOAPP_HUB_FRONT_DOOR_PORT=8000" in env
    assert "IMMOAPP_BACKEND_HOST_PORT=8000" in env
    assert "WEB_PORT=8000" in env
    assert (
        'Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "IMMOAPP_WEB_BIND_HOST" -Value "127.0.0.1"'
        in common
    )
    assert 'Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "IMMOAPP_CADDY_BIND_HOST"' in common
    assert (
        'Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "COMPOSE_PROFILES" -Value "hub-front-door"'
        in common
    )
    assert 'Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "DJANGO_DEBUG" -Value "0"' in common
    assert 'Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "DJANGO_ALLOWED_HOSTS"' in common


def test_docs_record_hub_m1_go_no_go_boundaries() -> None:
    checklist = _read("docs/guides/BETA_RELEASE_CHECKLIST.md")
    stack = _read("docs/guides/STACK.md")
    architecture = _read("docs/architecture/RUNTIME_AND_DATA_FLOWS.md")
    for text in (checklist, stack, architecture):
        assert "setup_office_hub.ps1" in text
        assert "hub_manager.ps1" in text
        assert "detect_hub_runtime.ps1" in text
    assert "Docker Desktop as a real-agency blocker" in checklist
    assert "manual_docker_desktop" in stack
    assert "Local HTTP is acceptable only for private LAN beta proof" in architecture
    assert "HUB_RUNTIME_PACKAGING.md" in _read(
        "docs/architecture/HUB_RUNTIME_PACKAGING.md"
    ) or "Hub Runtime Packaging" in _read("docs/architecture/HUB_RUNTIME_PACKAGING.md")
    assert "MinIO API/console" in stack


def test_managed_runtime_registration_and_network_boundary_scripts_exist() -> None:
    register = _read("scripts/register_managed_hub_runtime_provider.ps1")
    boundary = _read("scripts/verify_hub_network_boundary.ps1")
    build = _read("scripts/build_managed_hub_runtime_package.ps1")
    create_provenance = _read("scripts/create_managed_runtime_vendor_provenance.ps1")
    install = _read("scripts/install_managed_hub_runtime_provider.ps1")
    uninstall = _read("scripts/uninstall_managed_hub_runtime_provider.ps1")
    verify = _read("scripts/verify_managed_hub_runtime_provider.ps1")
    verify_provenance = _read("scripts/verify_managed_runtime_vendor_provenance.ps1")
    candidate = _read("scripts/run_managed_runtime_candidate_proof.ps1")
    for token in (
        "ConfirmManagedRuntimeProof",
        "Get-ImmoAppHubRuntimeProviderConfigPath",
        "Invoke-ImmoAppManagedRuntimeProviderRegistration",
        "Enter-ImmoAppProviderMutationLock",
        "ShouldProcess",
    ):
        assert token in register
    for token in (
        "immoapp_hub_network_boundary_evidence",
        "unsafe_publishers",
        "web_api_health_status",
        "web_api_lan_bind_status",
        "infra_exposure_status",
        "exposed_infra_services",
        "boundary_result",
        "reason_code",
        "web_health_unreachable",
        "approved_lan_facing_service",
        "infra_ports_policy",
        "firewall_status",
        "proof_scope",
        "local_compose_boundary",
        "external_lan_probe_performed",
        "external_lan_probe_required_for_real_lan_go",
        "front_door_url",
        "caddy_status",
        "backend_internal_status",
        "caddy_admin_lan_exposed",
        '"caddy"',
    ):
        assert token in boundary
    common = _read("scripts/common.ps1")
    for token in (
        "immoapp_managed_hub_runtime_package_inventory",
        "managed_runtime_artifact_missing",
        "forbidden_runtime_package_content",
        "forbidden_matches",
        "managed_runtime_package_path_mapping_failed",
        "source_tree_clean",
        "runtime_source_origin",
        "dirty_files_summary_count",
        "AllowExternalRuntimeSource",
        "VendorProvenanceJson",
        "AllowDirtyRuntimePackageProof",
        "AllowSourceCommitOverride",
    ):
        assert token in build
    for token in (
        ".git",
        ".tmp",
        "secrets",
        "Get-ImmoAppForbiddenRuntimePackageReason",
        "Get-ImmoAppStrictRuntimeTreeInventory",
        "Get-ImmoAppSafeZipInventory",
        "Write-ImmoAppSafeJson",
        "Assert-ImmoAppManagedRuntimePackageInventoryReady",
    ):
        assert token in common
    assert "function Assert-ManagedRuntimeInventory" not in _read("scripts/detect_hub_runtime.ps1")
    assert "function Assert-PackageInventoryReady" not in register
    for token in (
        "deprecated; delegating to register_managed_hub_runtime_provider.ps1",
        "register_managed_hub_runtime_provider.ps1",
        "ConfirmManagedRuntimeProof",
        "AllowTestRuntime",
        "PackageInventoryJson",
        "Production managed runtime provider requires -PackageInventoryJson",
        "-AllowTestOnlyPath",
    ):
        assert token in install
    assert "ConfirmManagedRuntimeProviderRemoval" in uninstall
    assert "removed_runtime_data = $false" in uninstall
    assert "immoapp_managed_hub_runtime_provider_verification" in verify
    assert "managed_runtime_proof_provider_verified" in verify
    assert "immoapp_managed_runtime_vendor_provenance" in create_provenance
    assert "immoapp_managed_runtime_vendor_provenance_verification" in verify_provenance
    for token in (
        "immoapp_managed_runtime_candidate_proof",
        "missing_artifacts",
        "candidate_validation_status",
        "provider_promotion_status",
        "provider_active_after_proof",
        "provider_config_sha256_final",
        "provider_final_state",
        "candidate_proof_run_id",
        "Enter-ImmoAppProviderMutationLock",
        "Exit-ImmoAppProviderMutationLock",
        "provider_lock_status",
        "provider_lock_released",
        "managed_runtime_candidate_validated_not_promoted",
        "Assert-ImmoAppStrictBackupRestoreEvidence",
        "Invoke-ImmoAppManagedRuntimeProviderRegistration",
        "Assert-ImmoAppProviderSnapshotPathSafe",
        "ConfirmLicenseDistributionApproved",
        "vendor_provenance_required_for_promotion",
        "inline_explicit_approval",
        "vendor_provenance.inline.json",
    ):
        assert token in candidate
    assert 'LicenseReviewStatus = "approved"' not in candidate
    assert "finally {" in candidate
    assert "provider_promoted = $providerPromoted" in candidate
    assert "provider_active_after_proof = $providerActiveAfterProof" in candidate
    common = _read("scripts/common.ps1")
    assert "immoapp_hub_runtime_provider_registration" in common
    assert "Docker Desktop executable cannot be registered" in common
    assert "function Invoke-ImmoAppManagedRuntimeProviderRegistration" in common
    assert "ProviderMutationLockToken" not in register
    assert "ProviderMutationLockToken" not in candidate


def test_detect_hub_runtime_rejects_fake_provider_without_package_inventory(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(
        tmp_path,
        provider_overrides={"package_inventory_path": "", "package_sha256": ""},
    )
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "managed_container_runtime"
    assert data["agency_install_status"] == "NO_GO"
    assert data["provider_config_valid"] is True
    assert data["reason_code"] == "managed_runtime_noncanonical_provider_config"


def test_detect_hub_runtime_test_programdata_root_is_internal_only(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(tmp_path)
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "managed_container_runtime"
    assert data["agency_install_status"] == "NO_GO"
    assert data["internal_proof_status"] == "GO"
    assert data["provider_config_valid"] is True
    assert data["provider_validation_status"] == "valid"
    assert data["reason_code"] == "managed_runtime_noncanonical_provider_config"
    assert data["runtime_root_source"] == "test_programdata_root"
    assert data["runtime_root_is_canonical"] is False


@pytest.mark.parametrize(
    ("provider_overrides", "inventory_overrides", "expected_reason"),
    [
        ({"user_visible_runtime": True}, None, "invalid_provider_config"),
        ({"api_token": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"apiKey": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"access_token": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"refresh_token": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"client_secret": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"private_key": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"certificate": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"cert": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"key_material": "not-allowed"}, None, "managed_runtime_secret_in_config"),
        ({"nested": {"apiKey": "not-allowed"}}, None, "managed_runtime_secret_in_config"),
    ],
)
def test_detect_hub_runtime_rejects_provider_shape_and_secret_violations(
    tmp_path: Path,
    provider_overrides: dict[str, object] | None,
    inventory_overrides: dict[str, object] | None,
    expected_reason: str,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(
        tmp_path,
        provider_overrides=provider_overrides,
        inventory_overrides=inventory_overrides,
    )
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "unavailable"
    assert data["agency_install_status"] == "NO_GO"
    assert data["provider_validation_status"] == "invalid"
    assert data["reason_code"] == expected_reason


def test_detect_hub_runtime_rejects_fake_native_windows_services_provider(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(
        tmp_path,
        provider_overrides={
            "provider_mode": "native_windows_services",
            "services_implemented": True,
            "services_health_checked": True,
        },
    )
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "native_windows_services"
    assert data["agency_install_status"] == "NO_GO"
    assert data["internal_proof_status"] == "NO_GO"
    assert data["reason_code"] == "native_services_deferred"


def test_detect_hub_runtime_rejects_noncanonical_provider_for_agency_go(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(tmp_path)
    noncanonical = tmp_path / "noncanonical_provider.json"
    noncanonical.write_text(provider.read_text(encoding="utf-8"), encoding="utf-8")
    data = _detect_provider(noncanonical, env=env, use_provider_arg=True)
    assert data["runtime_dependency_mode"] == "managed_container_runtime"
    assert data["internal_proof_status"] == "GO"
    assert data["agency_install_status"] == "NO_GO"
    assert data["provider_config_is_canonical"] is False
    assert data["reason_code"] == "managed_runtime_noncanonical_provider_config"


def test_detect_hub_runtime_rejects_provider_config_parent_junction(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(tmp_path)
    target = tmp_path / "provider-target"
    target.mkdir()
    copied = target / "hub_runtime_provider.json"
    copied.write_text(provider.read_text(encoding="utf-8"), encoding="utf-8")
    link = tmp_path / "provider-link"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    data = _detect_provider(link / "hub_runtime_provider.json", env=env, use_provider_arg=True)
    assert data["runtime_dependency_mode"] == "unavailable"
    assert data["agency_install_status"] == "NO_GO"
    assert data["provider_config_valid"] is False
    assert data["reason_code"] == "managed_runtime_provider_config_path_unsafe"


def test_detect_hub_runtime_rejects_tampered_package_artifact(tmp_path: Path) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    paths["package"].write_bytes(b"tampered-package")
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "managed_container_runtime"
    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] == "managed_runtime_noncanonical_provider_config"


def test_detect_hub_runtime_rejects_installed_runtime_hash_mismatch(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    paths["runtime"].write_text(
        paths["runtime"].read_text(encoding="utf-8") + "\r\nrem tampered\r\n",
        encoding="utf-8",
    )
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "managed_container_runtime"
    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] == "managed_runtime_noncanonical_provider_config"


def test_detect_hub_runtime_rejects_runtime_path_outside_approved_root(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(
        tmp_path,
        runtime_path=tmp_path / "outside-runtime" / "immoapp-runtime.cmd",
    )
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "unavailable"
    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] == "managed_runtime_proof_provider_path_not_approved"


def test_detect_hub_runtime_rejects_reparse_runtime_path(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    outside = tmp_path / "outside-runtime-target"
    outside.mkdir()
    _write_fake_runtime(outside / "immoapp-runtime.cmd")
    junction = paths["runtime_root"] / "runtime-junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True,
        capture_output=True,
        text=True,
    )
    runtime_via_junction = junction / "immoapp-runtime.cmd"
    runtime_sha = _sha256(runtime_via_junction)
    provider_data = json.loads(provider.read_text(encoding="utf-8"))
    provider_data["runtime_executable_path"] = str(runtime_via_junction)
    provider.write_text(json.dumps(provider_data), encoding="utf-8")
    inventory_path = paths["inventory"]
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["critical_executables"] = {
        "runtime_executable_relative_path": "runtime-junction/immoapp-runtime.cmd",
        "compose_executable_relative_path": "runtime-junction/immoapp-runtime.cmd",
    }
    inventory["files"] = [
        {
            "path": "runtime-junction/immoapp-runtime.cmd",
            "bytes": runtime_via_junction.stat().st_size,
            "sha256": runtime_sha,
        }
    ]
    inventory["total_bytes"] = runtime_via_junction.stat().st_size
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "unavailable"
    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] == "managed_runtime_reparse_point_not_allowed"


def test_detect_hub_runtime_rejects_user_visible_docker_desktop_path(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(
        tmp_path,
        runtime_path=tmp_path / "Docker" / "Docker" / "Docker Desktop.exe",
    )
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "unavailable"
    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] == "invalid_provider_config"


def test_detect_hub_runtime_marks_proof_only_provider_no_agency_go(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(
        tmp_path,
        provider_overrides={"proof_only": True},
        inventory_overrides={"proof_only": True},
    )
    data = _detect_provider(provider, env=env, use_provider_arg=False)
    assert data["runtime_dependency_mode"] == "managed_container_runtime"
    assert data["internal_proof_status"] == "GO"
    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] in {
        "managed_runtime_noncanonical_provider_config",
        "noncanonical_runtime_root",
    }
    assert data["provider"]["proof_only"] is True


def test_detect_hub_runtime_rejects_proof_only_runtime_outside_approved_roots_before_execution(
    tmp_path: Path,
) -> None:
    provider, env, _paths = _write_managed_provider_fixture(
        tmp_path,
        provider_overrides={"proof_only": True},
        inventory_overrides={"proof_only": True},
    )
    outside_runtime = tmp_path / "outside-runtime" / "evil-runtime.cmd"
    marker = tmp_path / "executed.marker"
    _write_marker_runtime(outside_runtime, marker)
    payload = json.loads(provider.read_text(encoding="utf-8"))
    payload["runtime_executable_path"] = str(outside_runtime)
    payload["install_root"] = str(outside_runtime.parent)
    provider.write_text(json.dumps(payload), encoding="utf-8")

    data = _detect_provider(provider, env=env, use_provider_arg=False)

    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] == "managed_runtime_proof_provider_path_not_approved"
    assert not marker.exists()


def test_detect_hub_runtime_rejects_invalid_provider_without_manual_fallback(
    tmp_path: Path,
) -> None:
    provider = tmp_path / "hub_runtime_provider.json"
    provider.write_text("{not-json", encoding="utf-8")
    data = _detect_provider(provider)
    assert data["runtime_dependency_mode"] == "unavailable"
    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] == "invalid_provider_config"


def test_collect_hub_install_evidence_requires_explicit_workstation_hub_url(
    tmp_path: Path,
) -> None:
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "collect_hub_install_evidence.ps1"),
            "-InstallRole",
            "workstation_only",
            "-OutputJson",
            str(tmp_path / "install.json"),
            "-InstallerSha256",
            "0" * 64,
        ],
        check=False,
    )
    assert result.returncode != 0
    assert "requires explicit HubBaseUrl" in (result.stderr + result.stdout)


def test_collect_hub_install_evidence_rejects_workstation_localhost_url(
    tmp_path: Path,
) -> None:
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "collect_hub_install_evidence.ps1"),
            "-InstallRole",
            "workstation_only",
            "-HubBaseUrl",
            "http://localhost:8000",
            "-OutputJson",
            str(tmp_path / "install.json"),
            "-InstallerSha256",
            "0" * 64,
        ],
        check=False,
    )
    assert result.returncode != 0
    assert "must use a Hub IP/hostname" in (result.stderr + result.stdout)


def test_collect_hub_install_evidence_uses_resolved_hub_url_for_localhost_flag(
    tmp_path: Path,
) -> None:
    runtime_detection = tmp_path / "runtime_detection.json"
    runtime_detection.write_text(
        json.dumps(
            {
                "kind": "immoapp_hub_runtime_detection",
                "runtime_dependency_mode": "manual_docker_desktop",
                "agency_install_status": "NO_GO",
                "internal_proof_status": "GO",
                "runtime_is_user_visible": True,
                "provider_validation_status": "missing",
                "reason_code": "manual_docker_desktop",
                "provider_config_path": "",
                "provider_config_present": False,
                "provider_config_valid": False,
                "provider": {},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "install.json"
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "collect_hub_install_evidence.ps1"),
            "-InstallRole",
            "workstation_only",
            "-HubBaseUrl",
            "http://192.168.1.20:8000/",
            "-OutputJson",
            str(output),
            "-RuntimeDetectionJson",
            str(runtime_detection),
            "-InstallerSha256",
            "0" * 64,
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(tmp_path / "ProgramData" / "ImmoApp"),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=True,
    )
    assert "Hub install proof_result=NO-GO" in result.stdout
    data = json.loads(output.read_text(encoding="utf-8-sig"))
    assert data["hub_base_url"] == "http://192.168.1.20:8000"
    assert data["backend_url_is_localhost"] is False


def test_install_managed_provider_refuses_production_without_inventory(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    provider.unlink()
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "install_managed_hub_runtime_provider.ps1"),
            "-RuntimeExecutablePath",
            str(paths["runtime"]),
            "-ConfirmManagedRuntimeProof",
            "-WhatIf",
        ],
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "Production managed runtime provider requires -PackageInventoryJson" in (
        result.stderr + result.stdout
    )


def test_register_managed_provider_requires_inventory_unless_test_only(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    provider.unlink()
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "register_managed_hub_runtime_provider.ps1"),
            "-RuntimeExecutablePath",
            str(paths["runtime"]),
            "-InstallRoot",
            str(paths["runtime_root"]),
            "-DataRoot",
            str(paths["data_root"]),
            "-LogsRoot",
            str(paths["logs_root"]),
            "-ConfirmManagedRuntimeProof",
        ],
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "Production managed runtime provider registration requires -PackageInventoryJson" in (
        result.stderr + result.stdout
    )
    assert not (tmp_path / "executed.txt").exists()


def test_register_managed_provider_rejects_before_executing_outside_runtime(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    provider.unlink()
    marker = tmp_path / "executed.txt"
    outside_runtime = tmp_path / "outside" / "immoapp-runtime.cmd"
    _write_marker_runtime(outside_runtime, marker)
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "register_managed_hub_runtime_provider.ps1"),
            "-RuntimeExecutablePath",
            str(outside_runtime),
            "-InstallRoot",
            str(paths["runtime_root"]),
            "-DataRoot",
            str(paths["data_root"]),
            "-LogsRoot",
            str(paths["logs_root"]),
            "-ConfirmManagedRuntimeProof",
        ],
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert not marker.exists()


def test_register_managed_provider_rejects_junction_before_execution(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    provider.unlink()
    marker = tmp_path / "executed.txt"
    outside = tmp_path / "runtime-target"
    outside.mkdir()
    _write_marker_runtime(outside / "immoapp-runtime.cmd", marker)
    junction = paths["runtime_root"] / "runtime-junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "register_managed_hub_runtime_provider.ps1"),
            "-RuntimeExecutablePath",
            str(junction / "immoapp-runtime.cmd"),
            "-InstallRoot",
            str(paths["runtime_root"]),
            "-DataRoot",
            str(paths["data_root"]),
            "-LogsRoot",
            str(paths["logs_root"]),
            "-ConfirmManagedRuntimeProof",
            "-AllowTestOnlyPath",
        ],
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "reparse point" in (result.stderr + result.stdout)
    assert not marker.exists()


def test_register_managed_provider_test_only_output_is_explicit_no_go(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    provider.unlink()
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "register_managed_hub_runtime_provider.ps1"),
            "-RuntimeExecutablePath",
            str(paths["runtime"]),
            "-InstallRoot",
            str(paths["runtime_root"]),
            "-DataRoot",
            str(paths["data_root"]),
            "-LogsRoot",
            str(paths["logs_root"]),
            "-ConfirmManagedRuntimeProof",
            "-AllowTestOnlyPath",
        ],
        env=env,
    )
    data = json.loads(result.stdout)
    assert data["provider_write_status"] == "GO"
    assert data["internal_proof_status"] == "GO"
    assert data["agency_install_status"] == "NO_GO"
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "proof_only_provider"
    assert data["proof_only"] is True
    assert data["provider_config_sha256_after_write"]


def test_register_managed_provider_whatif_never_reports_write_go(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    provider.unlink()
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "register_managed_hub_runtime_provider.ps1"),
            "-RuntimeExecutablePath",
            str(paths["runtime"]),
            "-InstallRoot",
            str(paths["runtime_root"]),
            "-DataRoot",
            str(paths["data_root"]),
            "-LogsRoot",
            str(paths["logs_root"]),
            "-ConfirmManagedRuntimeProof",
            "-AllowTestOnlyPath",
            "-WhatIf",
        ],
        env=env,
    )
    data = json.loads(result.stdout[result.stdout.find("{") :])
    assert data["provider_write_status"] == "not_written_whatif"
    assert data["internal_proof_status"] == "NO_GO"
    assert data["agency_install_status"] == "NO_GO"
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "whatif_not_written"
    assert not provider.exists()


def test_install_managed_provider_delegates_test_only_no_go_semantics(
    tmp_path: Path,
) -> None:
    provider, env, paths = _write_managed_provider_fixture(tmp_path)
    provider.unlink()
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "install_managed_hub_runtime_provider.ps1"),
            "-RuntimeExecutablePath",
            str(paths["runtime"]),
            "-ConfirmManagedRuntimeProof",
            "-AllowTestRuntime",
        ],
        env=env,
    )
    data = json.loads(result.stdout)
    assert data["agency_install_status"] == "NO_GO"
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "proof_only_provider"


def test_managed_runtime_package_rejects_forbidden_git_path_exactly(tmp_path: Path) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "package-output"
    runtime = source / "immoapp-runtime.cmd"
    _write_fake_runtime(runtime)
    forbidden = source / ".git" / "config"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text("not allowed", encoding="utf-8")
    result, data = _build_managed_runtime_package(
        source,
        output,
        "-AllowExternalRuntimeSource",
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        check=False,
    )
    assert result.returncode != 0
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "forbidden_runtime_package_content"
    assert {"path": ".git/config", "reason": "forbidden_runtime_package_path"} in data[
        "forbidden_matches"
    ]
    assert any(file["path"] == ".git/config" for file in data["files"])
    assert not Path(data["package_path"]).exists() if data["package_path"] else True


def test_managed_runtime_package_rejects_root_env_without_renaming(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "package-output"
    runtime = source / "immoapp-runtime.cmd"
    _write_fake_runtime(runtime)
    (source / ".env").write_text("SECRET=value", encoding="utf-8")
    result, data = _build_managed_runtime_package(
        source,
        output,
        "-AllowExternalRuntimeSource",
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        check=False,
    )
    assert result.returncode != 0
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "forbidden_runtime_package_content"
    assert {"path": ".env", "reason": "forbidden_sensitive_file"} in data["forbidden_matches"]
    assert any(file["path"] == ".env" for file in data["files"])
    assert not Path(data["package_path"]).exists() if data["package_path"] else True


def test_managed_runtime_package_refuses_nonempty_output_root_without_replace(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "package-output"
    output.mkdir()
    (output / "old.txt").write_text("stale", encoding="utf-8")
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_hub_runtime_package.ps1"),
            "-RuntimeSourceRoot",
            str(source),
            "-OutputRoot",
            str(output),
            "-AllowExternalRuntimeSource",
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(tmp_path),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    assert "OutputRoot is not empty" in (result.stderr + result.stdout)


def test_managed_runtime_package_rejects_reparse_output_root(tmp_path: Path) -> None:
    source = tmp_path / "runtime-source"
    target = tmp_path / "outside-output"
    output = tmp_path / "output-link"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    target.mkdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(output), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_hub_runtime_package.ps1"),
            "-RuntimeSourceRoot",
            str(source),
            "-OutputRoot",
            str(output),
            "-AllowExternalRuntimeSource",
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(tmp_path),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    assert "managed_runtime_output_root_reparse_point" in (result.stderr + result.stdout)


def test_managed_runtime_package_rejects_arbitrary_external_output_root(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "not-programdata-output"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_hub_runtime_package.ps1"),
            "-RuntimeSourceRoot",
            str(source),
            "-OutputRoot",
            str(output),
            "-AllowExternalRuntimeSource",
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
        ],
        check=False,
    )
    assert result.returncode != 0
    assert "managed_runtime_output_root_not_approved" in (result.stderr + result.stdout)


def test_managed_runtime_package_no_go_clears_stale_zip_with_replace(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "package-output"
    output.mkdir()
    stale_zip = output / "immoapp-managed-hub-runtime-proof.zip"
    stale_zip.write_bytes(b"old package")
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    (source / ".env").write_text("SECRET=value", encoding="utf-8")
    result, data = _build_managed_runtime_package(
        source,
        output,
        "-AllowReplaceOutputRoot",
        "-AllowExternalRuntimeSource",
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        check=False,
    )
    assert result.returncode != 0
    assert data["proof_result"] == "NO-GO"
    assert data["package_path"] == ""
    assert data["package_sha256"] == ""
    assert data["package_bytes"] == 0
    assert not stale_zip.exists()


def test_managed_runtime_package_git_failure_fails_closed(tmp_path: Path) -> None:
    source = REPO_ROOT / "rtproofgitfail_contract"
    output = tmp_path / "package-output"
    try:
        _write_fake_runtime(source / "immoapp-runtime.cmd")
        command = (
            "function git { $global:LASTEXITCODE = 1; return '' }; "
            f"& {_ps_quote(REPO_ROOT / 'scripts' / 'build_managed_hub_runtime_package.ps1')} "
            f"-RuntimeSourceRoot {_ps_quote(source)} "
            f"-OutputRoot {_ps_quote(output)} "
            "-RuntimeExecutableRelativePath 'immoapp-runtime.cmd'"
        )
        result = _run_powershell(
            ["-Command", command],
            env={
                "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(tmp_path),
                "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            },
            check=False,
        )
        assert result.returncode != 0
        data = json.loads(
            (output / "managed_hub_runtime_package_inventory.json").read_text(encoding="utf-8-sig")
        )
        assert data["proof_result"] == "NO-GO"
        assert data["source_tree_clean"] is False
        assert data["git_state"]["dirty_state_verified"] is False
        assert data["git_state"]["failure_reason"] in {
            "managed_runtime_git_unavailable",
            "managed_runtime_git_head_unverified",
            "managed_runtime_git_status_failed",
        }
    finally:
        shutil.rmtree(source, ignore_errors=True)


def test_managed_runtime_package_rejects_source_root_junction(tmp_path: Path) -> None:
    target = tmp_path / "runtime-target"
    output = tmp_path / "package-output"
    _write_fake_runtime(target / "immoapp-runtime.cmd")
    junction = tmp_path / "runtime-source-link"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    result, data = _build_managed_runtime_package(
        junction,
        output,
        "-AllowExternalRuntimeSource",
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        check=False,
    )
    assert result.returncode != 0
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "managed_runtime_source_root_reparse_point"
    assert data["package_path"] == ""


def test_managed_runtime_package_external_artifact_with_malformed_provenance_is_no_go(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "package-output"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    provenance = tmp_path / "bad-provenance.json"
    provenance.write_text(json.dumps({"kind": "wrong"}), encoding="utf-8")
    result, data = _build_managed_runtime_package(
        source,
        output,
        "-AllowExternalRuntimeSource",
        "-VendorProvenanceJson",
        str(provenance),
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        check=False,
    )
    assert result.returncode == 0
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] in {
        "managed_runtime_vendor_provenance_invalid",
        "managed_runtime_vendor_provenance_missing",
    }


@pytest.mark.parametrize(
    ("zip_entries", "expected_reason"),
    [
        ({"../evil.cmd": b"bad"}, "managed_runtime_vendor_zip_unsafe_path"),
        ({"secrets/token.txt": b"bad"}, "managed_runtime_vendor_zip_forbidden_content"),
    ],
)
def test_vendor_provenance_rejects_unsafe_or_forbidden_zip_entries(
    tmp_path: Path,
    zip_entries: dict[str, bytes],
    expected_reason: str,
) -> None:
    source = tmp_path / "runtime-source"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    runtime_root = programdata / "runtime"
    config_root = programdata / "config"
    runtime_root.mkdir(parents=True)
    config_root.mkdir(parents=True)
    artifact = runtime_root / "vendor-runtime.zip"
    with zipfile.ZipFile(artifact, "w") as bundle:
        for name, data in zip_entries.items():
            bundle.writestr(name, data)
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "create_managed_runtime_vendor_provenance.ps1"),
            "-ArtifactPath",
            str(artifact),
            "-ExtractedRuntimeRoot",
            str(source),
            "-VendorName",
            "Test Vendor",
            "-RuntimeName",
            "Test Runtime",
            "-RuntimeVersion",
            "1.0.0",
            "-RuntimeLicense",
            "Test License",
            "-InternalSourceReference",
            "test-fixture",
            "-ApprovalReason",
            "contract test",
            "-LicenseDistributionAllowed",
            "true",
            "-LicenseReviewStatus",
            "approved",
            "-ApprovedBy",
            "Release Engineering",
            "-OutputJson",
            str(config_root / "vendor-provenance.json"),
            "-ApprovedByImmoApp",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    assert expected_reason in (result.stderr + result.stdout)


def test_vendor_provenance_rejects_duplicate_zip_entry(tmp_path: Path) -> None:
    source = tmp_path / "runtime-source"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    runtime_root = programdata / "runtime"
    config_root = programdata / "config"
    runtime_root.mkdir(parents=True)
    config_root.mkdir(parents=True)
    artifact = runtime_root / "vendor-runtime.zip"
    with zipfile.ZipFile(artifact, "w") as bundle:
        bundle.writestr("immoapp-runtime.cmd", b"one")
        bundle.writestr("immoapp-runtime.cmd", b"two")
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "create_managed_runtime_vendor_provenance.ps1"),
            "-ArtifactPath",
            str(artifact),
            "-ExtractedRuntimeRoot",
            str(source),
            "-VendorName",
            "Test Vendor",
            "-RuntimeName",
            "Test Runtime",
            "-RuntimeVersion",
            "1.0.0",
            "-RuntimeLicense",
            "Test License",
            "-InternalSourceReference",
            "test-fixture",
            "-ApprovalReason",
            "contract test",
            "-LicenseDistributionAllowed",
            "true",
            "-LicenseReviewStatus",
            "approved",
            "-ApprovedBy",
            "Release Engineering",
            "-OutputJson",
            str(config_root / "vendor-provenance.json"),
            "-ApprovedByImmoApp",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    assert "managed_runtime_vendor_zip_duplicate_entry" in (result.stderr + result.stdout)


def test_strict_runtime_tree_inventory_rejects_child_junction(tmp_path: Path) -> None:
    root = tmp_path / "runtime-root"
    target = tmp_path / "outside-target"
    root.mkdir()
    _write_fake_runtime(root / "immoapp-runtime.cmd")
    _write_fake_runtime(target / "hidden.cmd")
    junction = root / "linked"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    command = (
        f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
        f"Get-ImmoAppStrictRuntimeTreeInventory -Root {_ps_quote(root)} -RequireNonEmpty"
    )
    result = _run_powershell(["-Command", command], check=False)
    assert result.returncode != 0
    assert "managed_runtime_tree_reparse_point" in (result.stderr + result.stdout)


def test_strict_runtime_tree_inventory_rejects_empty_tree(tmp_path: Path) -> None:
    root = tmp_path / "runtime-root"
    root.mkdir()
    command = (
        f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
        f"Get-ImmoAppStrictRuntimeTreeInventory -Root {_ps_quote(root)} -RequireNonEmpty"
    )
    result = _run_powershell(["-Command", command], check=False)
    assert result.returncode != 0
    assert "managed_runtime_tree_empty" in (result.stderr + result.stdout)


def test_safe_zip_inventory_enforces_size_count_and_ratio_limits(tmp_path: Path) -> None:
    cases: list[tuple[str, dict[str, bytes], list[str], str]] = [
        (
            "single",
            {"immoapp-runtime.cmd": b"123456789"},
            ["-MaxSingleFileBytes", "8"],
            "managed_runtime_vendor_zip_file_too_large",
        ),
        (
            "count",
            {"a.cmd": b"a", "b.cmd": b"b"},
            ["-MaxFileCount", "1"],
            "managed_runtime_vendor_zip_too_many_files",
        ),
        (
            "total",
            {"a.cmd": b"123456", "b.cmd": b"789012"},
            ["-MaxTotalBytes", "10"],
            "managed_runtime_vendor_zip_total_bytes_exceeded",
        ),
        (
            "ratio",
            {"immoapp-runtime.cmd": b"0" * 4096},
            ["-MaxCompressionRatio", "1"],
            "managed_runtime_vendor_zip_suspicious_compression_ratio",
        ),
    ]
    for name, entries, extra_args, expected in cases:
        artifact = tmp_path / f"{name}.zip"
        with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for entry_name, payload in entries.items():
                bundle.writestr(entry_name, payload)
        command = (
            f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
            f"Get-ImmoAppSafeZipInventory -ArtifactPath {_ps_quote(artifact)} {' '.join(extra_args)}"
        )
        result = _run_powershell(["-Command", command], check=False)
        assert result.returncode != 0, name
        assert expected in (result.stderr + result.stdout)


def test_safe_json_writer_rejects_reparse_output_parent(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    link = approved / "config-link"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        check=True,
        capture_output=True,
        text=True,
    )
    output = link / "provenance.json"
    command = (
        f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
        f"Write-ImmoAppSafeJson -Path {_ps_quote(output)} "
        f"-Payload ([ordered]@{{kind='test'}}) -ApprovedRoots @({_ps_quote(approved)})"
    )
    result = _run_powershell(["-Command", command], check=False)
    assert result.returncode != 0
    assert "safe_json_output" in (result.stderr + result.stdout)


def test_safe_json_writer_returns_verified_final_sha(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    output = approved / "evidence.json"
    command = (
        f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
        "$result = Write-ImmoAppSafeJson "
        f"-Path {_ps_quote(output)} "
        "-Payload ([ordered]@{kind='test'; value='safe'}) "
        f"-ApprovedRoots @({_ps_quote(approved)}); "
        "$result | ConvertTo-Json -Depth 4"
    )
    result = _run_powershell(["-Command", command])
    data = json.loads(result.stdout)
    assert data["path"] == str(output)
    assert data["sha256"] == _sha256(output)


def test_safe_json_writer_replaces_existing_file_with_verified_sha(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    output = approved / "evidence.json"
    command = (
        f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
        "Write-ImmoAppSafeJson "
        f"-Path {_ps_quote(output)} "
        "-Payload ([ordered]@{kind='test'; value='old'}) "
        f"-ApprovedRoots @({_ps_quote(approved)}) | Out-Null; "
        "$result = Write-ImmoAppSafeJson "
        f"-Path {_ps_quote(output)} "
        "-Payload ([ordered]@{kind='test'; value='new'}) "
        f"-ApprovedRoots @({_ps_quote(approved)}); "
        "$content = Get-Content -LiteralPath "
        f"{_ps_quote(output)} "
        "-Raw | ConvertFrom-Json; "
        "[ordered]@{write=$result; value=$content.value} | ConvertTo-Json -Depth 4"
    )
    result = _run_powershell(["-Command", command])
    data = json.loads(result.stdout)
    assert data["value"] == "new"
    assert data["write"]["path"] == str(output)
    assert data["write"]["sha256"] == _sha256(output)


def test_safe_json_writer_survives_concurrent_same_path_writes(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    output = approved / "evidence.json"
    processes = []
    for value in range(1, 13):
        command = (
            f". {_ps_quote(REPO_ROOT / 'scripts' / 'common.ps1')}; "
            "Write-ImmoAppSafeJson "
            f"-Path {_ps_quote(output)} "
            f"-Payload ([ordered]@{{kind='test'; value={value}}}) "
            f"-ApprovedRoots @({_ps_quote(approved)}) | Out-Null"
        )
        processes.append(
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=45)
        if process.returncode != 0:
            failures.append(stdout + stderr)
    assert not failures
    data = json.loads(output.read_text(encoding="utf-8"))
    assert str(data["value"]) in {str(value) for value in range(1, 13)}
    assert len(_sha256(output)) == 64


def test_vendor_provenance_rejects_mismatched_artifact_and_runtime_tree(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    other = tmp_path / "other-runtime"
    _write_fake_runtime(other / "different-runtime.cmd")
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    runtime_root = programdata / "runtime"
    config_root = programdata / "config"
    runtime_root.mkdir(parents=True)
    config_root.mkdir(parents=True)
    artifact = runtime_root / "vendor-runtime.zip"
    _write_runtime_zip(artifact, other)
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "create_managed_runtime_vendor_provenance.ps1"),
            "-ArtifactPath",
            str(artifact),
            "-ExtractedRuntimeRoot",
            str(source),
            "-VendorName",
            "Test Vendor",
            "-RuntimeName",
            "Test Runtime",
            "-RuntimeVersion",
            "1.0.0",
            "-RuntimeLicense",
            "Test License",
            "-InternalSourceReference",
            "test-fixture",
            "-ApprovalReason",
            "contract test",
            "-LicenseDistributionAllowed",
            "true",
            "-LicenseReviewStatus",
            "approved",
            "-ApprovedBy",
            "Release Engineering",
            "-OutputJson",
            str(config_root / "vendor-provenance.json"),
            "-ApprovedByImmoApp",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    assert "managed_runtime_vendor_inventory_hash_mismatch" in (result.stderr + result.stdout)


def test_vendor_provenance_rejects_missing_license_distribution_approval(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    runtime_root = programdata / "runtime"
    config_root = programdata / "config"
    runtime_root.mkdir(parents=True)
    config_root.mkdir(parents=True)
    artifact = runtime_root / "vendor-runtime.zip"
    _write_runtime_zip(artifact, source)
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "create_managed_runtime_vendor_provenance.ps1"),
            "-ArtifactPath",
            str(artifact),
            "-ExtractedRuntimeRoot",
            str(source),
            "-VendorName",
            "Test Vendor",
            "-RuntimeName",
            "Test Runtime",
            "-RuntimeVersion",
            "1.0.0",
            "-RuntimeLicense",
            "Test License",
            "-InternalSourceReference",
            "test-fixture",
            "-ApprovalReason",
            "contract test",
            "-OutputJson",
            str(config_root / "vendor-provenance.json"),
            "-ApprovedByImmoApp",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    assert "LicenseDistributionAllowed" in (result.stderr + result.stdout)


def test_managed_runtime_package_external_artifact_with_valid_provenance_builds_proof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    runtime_root = programdata / "runtime"
    config_root = programdata / "config"
    output = runtime_root / "package-output"
    runtime_root.mkdir(parents=True)
    config_root.mkdir(parents=True)
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    artifact = runtime_root / "vendor-runtime.zip"
    _write_runtime_zip(artifact, source)
    env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
    }
    provenance = config_root / "vendor-provenance.json"
    _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "create_managed_runtime_vendor_provenance.ps1"),
            "-ArtifactPath",
            str(artifact),
            "-ExtractedRuntimeRoot",
            str(source),
            "-VendorName",
            "Test Vendor",
            "-RuntimeName",
            "Test Runtime",
            "-RuntimeVersion",
            "1.0.0",
            "-RuntimeLicense",
            "Test License",
            "-ArtifactKind",
            "zip",
            "-InternalSourceReference",
            "test-fixture",
            "-ApprovalReason",
            "contract test",
            "-LicenseDistributionAllowed",
            "true",
            "-LicenseReviewStatus",
            "approved",
            "-ApprovedBy",
            "Release Engineering",
            "-OutputJson",
            str(provenance),
            "-ApprovedByImmoApp",
        ],
        env=env,
    )
    result, data = _build_managed_runtime_package(
        source,
        output,
        "-AllowExternalRuntimeSource",
        "-VendorProvenanceJson",
        str(provenance),
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        env=env,
    )
    assert result.returncode == 0
    assert data["proof_result"] == "GO"
    assert data["runtime_source_origin"] == "external_artifact"
    assert data["vendor_provenance_path"] == str(provenance)
    assert data["vendor_provenance_sha256"]
    assert data["extracted_inventory_sha256"]
    assert data["proof_only"] is True
    assert Path(data["package_path"]).exists()


def test_managed_runtime_package_external_artifact_is_internal_only_even_with_flag(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "package-output"
    runtime = source / "immoapp-runtime.cmd"
    _write_fake_runtime(runtime)
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_hub_runtime_package.ps1"),
            "-RuntimeSourceRoot",
            str(source),
            "-OutputRoot",
            str(output),
            "-AllowExternalRuntimeSource",
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(tmp_path),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
    )
    data = json.loads(result.stdout)
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "managed_runtime_external_artifact_requires_vendor_provenance"
    assert data["schema_version"] == 2
    assert data["package_file_count"] == 1
    assert data["package_bytes"] == 0
    assert data["source_tree_clean"] is True
    assert data["source_commit_override"] is False
    assert data["runtime_source_origin"] == "external_artifact"
    assert data["proof_only"] is True
    assert data["critical_executables"]["runtime_executable_relative_path"] == (
        "immoapp-runtime.cmd"
    )
    assert data["package_path"] == ""
    assert data["package_sha256"] == ""


def test_managed_runtime_package_without_source_is_honest_no_go() -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "build_managed_hub_runtime_package.ps1"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert data["kind"] == "immoapp_managed_hub_runtime_package_inventory"
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "managed_runtime_artifact_missing"


def test_managed_runtime_prototype_scaffold_is_never_agency_go() -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "prepare_managed_hub_runtime_prototype.ps1"),
            "-ConfirmManagedRuntimePrototype",
            "-ValidateOnly",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert data["proof_result"] == "NO-GO"
    assert data["agency_install_status"] == "NO_GO"
    assert data["agency_ready"] is False
    assert "provider_detection" in data["missing_proof_tracks"]
    assert "hub_startup_proof" in data["missing_proof_tracks"]
    assert data["next_commands"]
    assert any(
        "create_managed_runtime_vendor_provenance.ps1" in item for item in data["next_commands"]
    )


def test_managed_runtime_candidate_proof_without_artifact_is_no_go(tmp_path: Path) -> None:
    output = tmp_path / "ProgramData" / "ImmoApp" / "logs" / "candidate.json"
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "run_managed_runtime_candidate_proof.ps1"),
            "-ConfirmManagedRuntimeCandidateProof",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    data = json.loads(output.read_text(encoding="utf-8-sig"))
    assert data["proof_result"] == "NO-GO"
    assert data["candidate_validation_status"] == "NO-GO"
    assert data["provider_promotion_status"] == "not_requested"
    assert data["provider_active_after_proof"] is False
    assert data["agency_install_status"] == "NO_GO"
    assert data["reason_code"] == "managed_runtime_candidate_missing_artifacts"
    assert data["missing_artifacts"] == ["runtime_zip_candidate"]
    assert data["provider_restored"] is True
    assert data["provider_final_state"] == "missing"
    assert data["provider_config_sha256_final"] == ""
    assert re.fullmatch(r"[0-9a-f]{32}", data["candidate_proof_run_id"])
    assert data["provider_lock_status"] == "acquired"
    assert data["provider_lock_released"] is True


@pytest.mark.parametrize(
    ("overrides", "expected", "reason_code"),
    (
        (
            {"candidate_proof_run_id": "stale-run"},
            {"ExpectedCandidateProofRunId": "candidate-run"},
            "backup_restore_candidate_proof_run_id_mismatch",
        ),
        (
            {"provider_config_sha256_at_backup": "c" * 64},
            {"ExpectedProviderConfigSha256": "d" * 64},
            "backup_restore_provider_sha_mismatch",
        ),
        (
            {"source_commit_sha": "b" * 40},
            {"ExpectedSourceCommitSha": "a" * 40},
            "backup_restore_source_commit_mismatch",
        ),
        (
            {"installer_sha256": "1" * 64},
            {"ExpectedInstallerSha256": "2" * 64},
            "backup_restore_installer_sha_mismatch",
        ),
        (
            {"candidate_proof_run_id": ""},
            {"ExpectedCandidateProofRunId": "candidate-run"},
            "backup_restore_candidate_proof_run_id_missing",
        ),
        (
            {"runtime_dependency_mode": "manual_docker_desktop"},
            {"ExpectedRuntimeDependencyMode": "managed_container_runtime"},
            "backup_restore_runtime_mode_mismatch",
        ),
    ),
)
def test_strict_backup_restore_evidence_rejects_candidate_identity_mismatch(
    tmp_path: Path,
    overrides: dict[str, object],
    expected: dict[str, str],
    reason_code: str,
) -> None:
    provider_path = tmp_path / "ProgramData" / "ImmoApp" / "config" / "hub_runtime_provider.json"
    payload: dict[str, object] = {
        "source_commit_sha": "a" * 40,
        "installer_sha256": "2" * 64,
        "candidate_proof_run_id": "candidate-run",
        "runtime_dependency_mode": "managed_container_runtime",
        "provider_config_sha256_at_backup": "d" * 64,
        "provider_config_path": str(provider_path),
        "hub_runtime_provider_mode": "managed_container_runtime",
        "backup_started_at_utc": "2026-01-01T00:00:00Z",
        "restore_verified_at_utc": "2026-01-01T00:01:00Z",
    }
    payload.update(overrides)
    evidence = _write_backup_restore_evidence(tmp_path, payload)
    check = _strict_backup_check(
        evidence,
        ExpectedSourceCommitSha=expected.get("ExpectedSourceCommitSha", "a" * 40),
        ExpectedInstallerSha256=expected.get("ExpectedInstallerSha256", "2" * 64),
        ExpectedCandidateProofRunId=expected.get("ExpectedCandidateProofRunId", "candidate-run"),
        ExpectedRuntimeDependencyMode=expected.get(
            "ExpectedRuntimeDependencyMode", "managed_container_runtime"
        ),
        ExpectedProviderConfigSha256=expected.get("ExpectedProviderConfigSha256", "d" * 64),
        ExpectedProviderConfigPath=str(provider_path),
        ExpectedHubRuntimeProviderMode="managed_container_runtime",
    )
    assert check["ok"] is False
    assert check["reason_code"] == reason_code


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    (
        (
            {"backup_bundle_path": ""},
            "backup_restore_artifact_proof_missing",
        ),
        (
            {"backup_bundle_path": "C:/does/not/exist/immoapp-backup.zip"},
            "backup_bundle_missing",
        ),
        (
            {
                "backup_bundle_path": "",
                "remote_evidence": True,
                "copied_artifact_sha256": "1" * 64,
                "copied_artifact_reference": "remote://bundle",
                "remote_machine_name": "REMOTE-HUB",
                "collected_at_utc": "2026-01-01T00:00:00Z",
            },
            "backup_restore_remote_artifact_proof_missing",
        ),
        (
            {
                "backup_bundle_path": "",
                "remote_evidence": True,
                "evidence_file_sha256": "2" * 64,
                "copied_artifact_sha256": "1" * 64,
                "copied_artifact_reference": "remote://bundle",
                "remote_machine_name": "REMOTE-HUB",
                "collected_at_utc": "2026-01-01T00:00:00Z",
            },
            "backup_restore_remote_artifact_sha_mismatch",
        ),
    ),
)
def test_strict_backup_restore_evidence_requires_local_or_remote_artifact_proof(
    tmp_path: Path,
    overrides: dict[str, object],
    reason_code: str,
) -> None:
    evidence = _write_backup_restore_evidence(tmp_path, overrides)
    check = _strict_backup_check(evidence)
    assert check["ok"] is False
    assert check["reason_code"] == reason_code


@pytest.mark.parametrize(
    "overrides",
    (
        {"status": "GO", "proof_result": ""},
        {"status": "GO", "proof_result": "NO-GO"},
    ),
)
def test_strict_backup_restore_evidence_requires_explicit_proof_result_go(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    evidence = _write_backup_restore_evidence(tmp_path, overrides)
    check = _strict_backup_check(evidence)
    assert check["ok"] is False
    assert check["reason_code"] == "backup_restore_proof_result_missing"


def test_strict_backup_restore_evidence_accepts_explicit_proof_result_go(
    tmp_path: Path,
) -> None:
    evidence = _write_backup_restore_evidence(tmp_path, {"status": "NO-GO"})
    check = _strict_backup_check(evidence)
    assert check["ok"] is True


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    (
        (
            {"status": "GO", "proof_result": ""},
            "backup_restore_proof_result_missing",
        ),
        (
            {
                "kind": "immoapp_beta_release_backup_restore_evidence",
                "schema_version": 1,
                "proof_result": "GO",
                "restore_database": "",
                "storage_objects_checked": 0,
                "storage_objects_hash_verified": 0,
            },
            "backup_restore_database_missing",
        ),
        ({"storage_objects_hash_verified": 0}, "backup_restore_hash_verification_incomplete"),
        (
            {"live_source_bucket_used_as_restore_target": True},
            "source_bucket_used_as_restore_target",
        ),
        ({"isolated_restore_bucket": "immoapp"}, "backup_restore_bucket_not_isolated"),
        ({"restore_database": ""}, "backup_restore_database_missing"),
    ),
)
def test_managed_runtime_candidate_proof_reuses_strict_backup_restore_evidence(
    tmp_path: Path,
    overrides: dict[str, object],
    reason_code: str,
) -> None:
    output = tmp_path / "ProgramData" / "ImmoApp" / "logs" / "candidate.json"
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    backup = _write_backup_restore_evidence(tmp_path, overrides)
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "run_managed_runtime_candidate_proof.ps1"),
            "-ConfirmManagedRuntimeCandidateProof",
            "-BackupRestoreEvidenceJson",
            str(backup),
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    data = json.loads(output.read_text(encoding="utf-8-sig"))
    backup_phase = next(phase for phase in data["phases"] if phase["name"] == "backup_restore")
    assert backup_phase["status"] == "NO-GO"
    assert backup_phase["reason_code"] == reason_code


def test_managed_runtime_candidate_proof_requires_license_approval_or_provenance(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    source = tmp_path / "runtime-source"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    artifact = programdata / "runtime" / "candidate.zip"
    _write_runtime_zip(artifact, source)
    output = programdata / "logs" / "candidate.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "run_managed_runtime_candidate_proof.ps1"),
            "-ConfirmManagedRuntimeCandidateProof",
            "-RuntimeZipArtifact",
            str(artifact),
            "-ExtractedRuntimeRoot",
            str(source),
            "-SourceCommitSha",
            "a" * 40,
            "-InstallerSha256",
            "b" * 64,
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    data = json.loads(output.read_text(encoding="utf-8-sig"))
    assert data["provenance_source"] == "missing"
    provenance_phase = next(
        phase for phase in data["phases"] if phase["name"] == "vendor_provenance"
    )
    assert provenance_phase["reason_code"] == "license_approval_missing"


def test_managed_runtime_candidate_proof_records_inline_license_approval_explicitly(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    shared_provenance = programdata / "config" / "managed_runtime_vendor_provenance.json"
    shared_provenance.parent.mkdir(parents=True)
    shared_provenance.write_text('{"kind":"trusted_existing_provenance"}', encoding="utf-8")
    shared_sha = _sha256(shared_provenance)
    source = tmp_path / "runtime-source"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    artifact = programdata / "runtime" / "candidate.zip"
    _write_runtime_zip(artifact, source)
    output = programdata / "logs" / "candidate.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "run_managed_runtime_candidate_proof.ps1"),
            "-ConfirmManagedRuntimeCandidateProof",
            "-ConfirmLicenseDistributionApproved",
            "-LicenseReviewStatus",
            "approved",
            "-ApprovedBy",
            "Release Engineering",
            "-ApprovalReason",
            "contract test",
            "-VendorName",
            "Test Vendor",
            "-RuntimeName",
            "Test Runtime",
            "-RuntimeVersion",
            "1.0.0",
            "-RuntimeLicense",
            "Test License",
            "-InternalSourceReference",
            "test fixture",
            "-RuntimeZipArtifact",
            str(artifact),
            "-ExtractedRuntimeRoot",
            str(source),
            "-SourceCommitSha",
            (subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()),
            "-InstallerSha256",
            "b" * 64,
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    data = json.loads(output.read_text(encoding="utf-8-sig"))
    assert data["provenance_source"] == "inline_explicit_approval"
    assert data["license_review_status"] == "approved"
    assert data["vendor_provenance_path"] != str(shared_provenance)
    assert data["candidate_proof_run_id"] in data["vendor_provenance_path"]
    assert _sha256(shared_provenance) == shared_sha
    generated = json.loads(Path(data["vendor_provenance_path"]).read_text(encoding="utf-8-sig"))
    assert generated["proof_only"] is True
    provenance_phase = next(
        phase for phase in data["phases"] if phase["name"] == "vendor_provenance"
    )
    assert provenance_phase["reason_code"] == "inline_explicit_license_approval_recorded"
    assert data["agency_install_status"] == "NO_GO"


def test_managed_runtime_candidate_proof_rejects_provider_snapshot_reparse_parent(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    outside = tmp_path / "outside-config"
    outside.mkdir(parents=True)
    config_link = programdata / "config"
    config_link.parent.mkdir(parents=True)
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(config_link), str(outside)],
        check=True,
        capture_output=True,
        text=True,
    )
    output = programdata / "logs" / "candidate.json"
    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "run_managed_runtime_candidate_proof.ps1"),
            "-ConfirmManagedRuntimeCandidateProof",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    assert "managed_runtime_provider_config_path_unsafe" in (
        result.stderr + result.stdout
    ) or "runtime_layout_foundation_directories_unsafe" in (result.stderr + result.stdout)


def test_managed_runtime_candidate_proof_restores_existing_provider_on_failure(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    provider = programdata / "config" / "hub_runtime_provider.json"
    provider.parent.mkdir(parents=True)
    original = {"kind": "existing_provider", "value": "do-not-change"}
    provider.write_text(json.dumps(original), encoding="utf-8")
    original_sha = _sha256(provider)
    output = programdata / "logs" / "candidate.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "run_managed_runtime_candidate_proof.ps1"),
            "-ConfirmManagedRuntimeCandidateProof",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    data = json.loads(output.read_text(encoding="utf-8-sig"))
    assert data["provider_restored"] is True
    assert data["provider_lock_status"] == "acquired"
    assert data["provider_lock_released"] is True
    assert data["provider_promoted"] is False
    assert data["provider_promotion_status"] == "not_requested"
    assert data["provider_active_after_proof"] is False
    assert data["provider_final_state"] == "restored"
    assert data["provider_config_sha256_final"] == original_sha
    assert data["provider_snapshot"]["sha256"] == original_sha
    assert json.loads(provider.read_text(encoding="utf-8-sig")) == original
    assert _sha256(provider) == original_sha


def test_managed_runtime_candidate_proof_restores_after_post_registration_failure(
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    provider = programdata / "config" / "hub_runtime_provider.json"
    provider.parent.mkdir(parents=True)
    original = {"kind": "existing_provider", "value": "restore-after-registration"}
    provider.write_text(json.dumps(original), encoding="utf-8")
    original_sha = _sha256(provider)
    source = programdata / "runtime" / "candidate-source"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    artifact = programdata / "runtime" / "candidate.zip"
    _write_runtime_zip(artifact, source)
    output = programdata / "logs" / "candidate.json"

    result = _run_powershell(
        [
            "-File",
            str(REPO_ROOT / "scripts" / "run_managed_runtime_candidate_proof.ps1"),
            "-ConfirmManagedRuntimeCandidateProof",
            "-ConfirmLicenseDistributionApproved",
            "-LicenseReviewStatus",
            "approved",
            "-ApprovedBy",
            "Release Engineering",
            "-ApprovalReason",
            "contract test",
            "-VendorName",
            "Test Vendor",
            "-RuntimeName",
            "Test Runtime",
            "-RuntimeVersion",
            "1.0.0",
            "-RuntimeLicense",
            "Test License",
            "-InternalSourceReference",
            "test fixture",
            "-RuntimeZipArtifact",
            str(artifact),
            "-ExtractedRuntimeRoot",
            str(source),
            "-SourceCommitSha",
            subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "-InstallerSha256",
            "b" * 64,
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
            "-OutputJson",
            str(output),
        ],
        env={
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            "IMMOAPP_TEST_CANDIDATE_FAIL_AFTER_PROVIDER_REGISTRATION": "1",
        },
        check=False,
    )
    assert result.returncode != 0
    data = json.loads(output.read_text(encoding="utf-8-sig"))
    assert data["provider_restored"] is True
    assert data["provider_promoted"] is False
    assert data["provider_final_state"] == "restored"
    assert data["provider_config_sha256_final"] == original_sha
    assert json.loads(provider.read_text(encoding="utf-8-sig")) == original
    assert _sha256(provider) == original_sha
    provider_phases = [
        phase for phase in data["phases"] if phase["name"] == "provider_registration"
    ]
    assert any(phase["status"] == "GO" for phase in provider_phases)
    assert any(
        "injected_failure_after_provider_registration" in phase["reason"]
        for phase in provider_phases
    )


def test_managed_runtime_package_external_source_requires_explicit_flag(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "package-output"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    result, data = _build_managed_runtime_package(
        source,
        output,
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        check=False,
    )
    assert result.returncode == 0
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "managed_runtime_external_source_not_allowed"
    assert data["runtime_source_origin"] == "external_artifact"


def test_managed_runtime_package_source_commit_override_is_internal_only(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runtime-source"
    output = tmp_path / "package-output"
    _write_fake_runtime(source / "immoapp-runtime.cmd")
    _result, data = _build_managed_runtime_package(
        source,
        output,
        "-AllowExternalRuntimeSource",
        "-SourceCommitSha",
        "b" * 40,
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        check=False,
    )
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "managed_runtime_source_commit_override_not_allowed"

    output_with_override = tmp_path / "package-output-override"
    _result, data = _build_managed_runtime_package(
        source,
        output_with_override,
        "-AllowExternalRuntimeSource",
        "-SourceCommitSha",
        "b" * 40,
        "-AllowSourceCommitOverride",
        "-RuntimeExecutableRelativePath",
        "immoapp-runtime.cmd",
        check=False,
    )
    assert data["proof_result"] == "NO-GO"
    assert data["reason_code"] == "managed_runtime_source_commit_override"
    assert data["proof_only"] is True
    assert data["source_commit_override"] is True


def test_managed_runtime_package_dirty_repo_source_is_not_agency_ready(
    tmp_path: Path,
) -> None:
    source = REPO_ROOT / "rtproofdirty_contract"
    output = tmp_path / "package-output"
    try:
        _write_fake_runtime(source / "immoapp-runtime.cmd")
        _result, data = _build_managed_runtime_package(
            source,
            output,
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
            check=False,
        )
        assert data["proof_result"] == "NO-GO"
        assert data["reason_code"] == "forbidden_runtime_package_content"
        assert data["runtime_source_origin"] == "repo"
        assert data["source_tree_clean"] is False
        assert {"path": "immoapp-runtime.cmd", "reason": "untracked_source_file"} in data[
            "forbidden_matches"
        ]

        proof_output = tmp_path / "package-output-proof"
        _result, proof_data = _build_managed_runtime_package(
            source,
            proof_output,
            "-AllowDirtyRuntimePackageProof",
            "-RuntimeExecutableRelativePath",
            "immoapp-runtime.cmd",
            check=False,
        )
        assert proof_data["proof_result"] == "NO-GO"
        assert proof_data["reason_code"] == "forbidden_runtime_package_content"
        assert proof_data["proof_only"] is False
    finally:
        shutil.rmtree(source, ignore_errors=True)
