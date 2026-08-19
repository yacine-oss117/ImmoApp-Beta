from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from app.tests.e2e_desktop.pages import login_to_main_window
from app.tests.e2e_desktop.runtime import (
    DEFAULT_API_TIMEOUT_SECONDS,
    DesktopLaunchOptions,
    DesktopSession,
    format_api_timeout_seconds,
)
from app.tests.e2e_desktop.ui import wait_for, write_text_file

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.installed_desktop,
]


def _required_env_path(name: str) -> Path:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        pytest.skip(f"{name} is required for installed desktop E2E.")
    path = Path(raw).resolve()
    if not path.exists():
        pytest.fail(f"{name} does not exist: {path}")
    return path


def _required_env_text(name: str) -> str:
    value = str(os.environ.get(name, "") or "").strip()
    if not value:
        pytest.skip(f"{name} is required for installed desktop E2E.")
    return value


def _run_powershell(
    repo_root: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def _install_location() -> Path:
    raw = str(os.environ.get("IMMOAPP_E2E_INSTALL_LOCATION", "") or "").strip()
    if raw:
        return Path(raw).resolve()
    local_appdata = Path(os.environ["LOCALAPPDATA"])
    return local_appdata / "Programs" / "ImmoApp Beta"


def _install_desktop_only(
    installer: Path,
    *,
    install_log: Path,
) -> subprocess.CompletedProcess[str]:
    install_log.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CURRENTUSER",
            "/IMMOAPPINSTALLMODE=desktop_only",
            "/TASKS=desktopicon",
            f"/LOG={install_log}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )


def _collect_install_lifecycle(
    repo_root: Path,
    *,
    installer: Path,
    installer_sha256: str,
    source_commit_sha: str,
    install_location: Path,
    install_log: Path,
    output_json: Path,
    backend_url: str,
) -> dict[str, Any]:
    result = _run_powershell(
        repo_root,
        [
            "-File",
            str(repo_root / "scripts" / "collect_install_lifecycle_evidence.ps1"),
            "-Mode",
            "post_install",
            "-InstallerPath",
            str(installer),
            "-InstallerSha256",
            installer_sha256,
            "-SourceCommitSha",
            source_commit_sha,
            "-BackendUrl",
            backend_url,
            "-InstallLocation",
            str(install_location),
            "-InstallLogPath",
            str(install_log),
            "-OutputJson",
            str(output_json),
        ],
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = _read_json(output_json)
    assert payload["install_mechanics_status"] == "GO"
    assert payload["phases"]["post_install"]["installed_exe_present"] is True
    return payload


def _collect_installed_inventory(
    repo_root: Path,
    *,
    installer: Path,
    installer_sha256: str,
    source_commit_sha: str,
    install_location: Path,
    output_json: Path,
    build_summary: Path | None,
) -> dict[str, Any]:
    args = [
        "-File",
        str(repo_root / "scripts" / "collect_installed_app_inventory.ps1"),
        "-InstallLocation",
        str(install_location),
        "-InstallerPath",
        str(installer),
        "-ExpectedInstallerSha256",
        installer_sha256,
        "-ExpectedSourceCommitSha",
        source_commit_sha,
        "-OutputJson",
        str(output_json),
    ]
    if build_summary is not None:
        args.extend(["-BuildSummaryJson", str(build_summary)])
    result = _run_powershell(repo_root, args, timeout=240)
    assert result.returncode == 0, result.stderr + result.stdout
    payload = _read_json(output_json)
    assert payload["proof_result"] == "GO"
    assert payload["source_commit_sha"] == source_commit_sha
    assert payload["installer_sha256"] == installer_sha256
    assert payload["forbidden_path_count"] == 0
    assert payload["installed_exe_sha256"]
    return payload


def _configure_installed_client_front_door(
    repo_root: Path,
    *,
    appdata_root: Path,
    front_door_url: str,
    username: str,
) -> Path:
    env = os.environ.copy()
    env["IMMOAPP_APPDATA_ROOT"] = str(appdata_root)
    result = _run_powershell(
        repo_root,
        [
            "-File",
            str(repo_root / "scripts" / "set_client_api_endpoint.ps1"),
            "-BaseUrl",
            front_door_url,
            "-Username",
            username,
            "-RememberSession",
            "-AllowLocalHub",
            "-ConnectionSource",
            "installed_desktop_e2e",
        ],
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return appdata_root / "config" / "client_api.json"


def _collect_installed_front_door_evidence(
    repo_root: Path,
    *,
    installed_exe: Path,
    front_door_url: str,
    installer_sha256: str,
    source_commit_sha: str,
    output_json: Path,
    expected_config: Path,
    inventory_json: Path,
) -> dict[str, Any]:
    result = _run_powershell(
        repo_root,
        [
            "-File",
            str(repo_root / "scripts" / "collect_installed_desktop_front_door_evidence.ps1"),
            "-InstalledExePath",
            str(installed_exe),
            "-FrontDoorUrl",
            front_door_url,
            "-InstallerSha256",
            installer_sha256,
            "-SourceCommitSha",
            source_commit_sha,
            "-ExpectedConfigPath",
            str(expected_config),
            "-InstalledInventoryJson",
            str(inventory_json),
            "-OutputJson",
            str(output_json),
        ],
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = _read_json(output_json)
    assert payload["proof_result"] == "GO"
    assert payload["health_status"] == 200
    assert payload["identity_status"] == 200
    assert payload["front_door_header"].lower() == "caddy"
    assert payload["persisted_client_base_url"] == front_door_url.rstrip("/")
    assert payload["connection_source"] != "local_dev_unverified"
    return payload


def _launch_installed_desktop(
    *,
    installed_exe: Path,
    appdata_root: Path,
    artifact_dir: Path,
    front_door_url: str,
    api_timeout_seconds: float,
) -> DesktopSession:
    for relative in ("cache", "config", "logs", "media", "tmp", "tools", "backups"):
        (appdata_root / relative).mkdir(parents=True, exist_ok=True)
    write_text_file(
        appdata_root / "config" / "onboarding_state.json",
        json.dumps({"quick_start_seen": True}, indent=2, ensure_ascii=True),
    )
    token = uuid.uuid4().hex[:8]
    env = os.environ.copy()
    env["IMMOAPP_APPDATA_ROOT"] = str(appdata_root)
    env["IMMOAPP_QSETTINGS_ORG"] = f"ImmoAppInstalledE2E_{token}"
    env["IMMOAPP_QSETTINGS_APP"] = "InstalledDesktop"
    env["IMMOAPP_DISABLE_KEYRING"] = "1"
    env["IMMOAPP_E2E_TEST_MODE"] = "1"
    env["IMMOAPP_API_TIMEOUT"] = format_api_timeout_seconds(api_timeout_seconds)
    for name in (
        "IMMOAPP_API_BASE_URL",
        "IMMOAPP_API_USERNAME",
        "IMMOAPP_API_PASSWORD",
        "IMMOAPP_API_TOKEN",
        "IMMOAPP_API_SCHEMA",
    ):
        env.pop(name, None)
    process = subprocess.Popen(
        [str(installed_exe)],
        cwd=installed_exe.parent,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    options = DesktopLaunchOptions(
        client_python=installed_exe,
        repo_root=installed_exe.parent,
        appdata_root=appdata_root,
        artifact_dir=artifact_dir,
        qsettings_org=env["IMMOAPP_QSETTINGS_ORG"],
        qsettings_app=env["IMMOAPP_QSETTINGS_APP"],
        base_url=front_door_url,
        preseed_api=False,
        preseed_quick_start=False,
        api_timeout_seconds=api_timeout_seconds,
    )
    session = DesktopSession(
        options=options,
        process=process,
        gui_pid=process.pid,
        stdio_handle=None,
    )
    wait_for(
        "installed desktop initial surface",
        lambda: (
            session.try_window(auto_id="immoMainWindow", timeout=0.3)
            or session.try_window(auto_id="immoLoginDialog", timeout=0.3)
            or session.try_window(title_re=".*Get started.*", timeout=0.3)
        ),
        timeout=60.0,
    )
    return session


def test_current_installer_installs_and_installed_desktop_reaches_hub_front_door(
    repo_root: Path,
    e2e_base_url: str,
    e2e_front_door_url: str,
    e2e_api_timeout_seconds: float,
    artifact_dir: Path,
    make_backend_user: Any,
) -> None:
    installer = _required_env_path("IMMOAPP_E2E_INSTALLER_PATH")
    installer_sha256 = _required_env_text("IMMOAPP_E2E_INSTALLER_SHA256")
    source_commit_sha = _required_env_text("IMMOAPP_E2E_INSTALLER_SOURCE_COMMIT_SHA")
    build_summary_raw = str(os.environ.get("IMMOAPP_E2E_INSTALLER_BUILD_SUMMARY", "") or "").strip()
    build_summary = Path(build_summary_raw).resolve() if build_summary_raw else None
    if build_summary is not None and not build_summary.exists():
        pytest.fail(f"IMMOAPP_E2E_INSTALLER_BUILD_SUMMARY does not exist: {build_summary}")

    install_location = _install_location()
    install_log = artifact_dir / "installer.log"
    install_result = _install_desktop_only(installer, install_log=install_log)
    assert install_result.returncode == 0, install_result.stderr + install_result.stdout

    lifecycle_json = artifact_dir / "install_lifecycle_post_install.json"
    _collect_install_lifecycle(
        repo_root,
        installer=installer,
        installer_sha256=installer_sha256,
        source_commit_sha=source_commit_sha,
        install_location=install_location,
        install_log=install_log,
        output_json=lifecycle_json,
        backend_url=e2e_base_url,
    )

    inventory_json = artifact_dir / "installed_inventory.json"
    inventory = _collect_installed_inventory(
        repo_root,
        installer=installer,
        installer_sha256=installer_sha256,
        source_commit_sha=source_commit_sha,
        install_location=install_location,
        output_json=inventory_json,
        build_summary=build_summary,
    )
    installed_exe = Path(str(inventory["installed_exe_path"]))
    assert installed_exe == install_location / "ImmoApp.exe"
    assert installed_exe.is_file()
    assert (install_location / "ImmoApp Hub Manager.exe").is_file()

    user = make_backend_user(prefix="e2e_installed_desktop")
    appdata_root = artifact_dir / "installed_appdata"
    client_config = _configure_installed_client_front_door(
        repo_root,
        appdata_root=appdata_root,
        front_door_url=e2e_front_door_url,
        username=user.username,
    )
    front_door_json = artifact_dir / "installed_front_door.json"
    _collect_installed_front_door_evidence(
        repo_root,
        installed_exe=installed_exe,
        front_door_url=e2e_front_door_url,
        installer_sha256=installer_sha256,
        source_commit_sha=source_commit_sha,
        output_json=front_door_json,
        expected_config=client_config,
        inventory_json=inventory_json,
    )

    session = _launch_installed_desktop(
        installed_exe=installed_exe,
        appdata_root=appdata_root,
        artifact_dir=artifact_dir / "installed_desktop_session",
        front_door_url=e2e_front_door_url,
        api_timeout_seconds=e2e_api_timeout_seconds or DEFAULT_API_TIMEOUT_SECONDS,
    )
    try:
        main = login_to_main_window(
            session,
            username=user.username,
            password=user.password,
            base_url=e2e_front_door_url,
        )
        wait_for("installed desktop main tabs", lambda: main.tabs, timeout=30.0)
    finally:
        session.close()
