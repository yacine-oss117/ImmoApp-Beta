from __future__ import annotations

import ctypes
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.tests.e2e_desktop import backend
from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver
from app.tests.e2e_desktop.installed_hub_manager_backend import (
    ManagedOwner,
    managed_user_by_email,
    wait_for_front_door,
)
from app.tests.e2e_desktop.installed_hub_manager_test_support import (
    HUB_MANAGER_OUTPUT_DIR,
    assert_installed_build_identity,
    installed_hub_manager_path,
    prior_mtime_ns,
    read_json,
    required_env_text,
    wait_for_evidence,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.installed_hub_manager,
]


def _seed_stale_firewall_rule(*, expected_port: int) -> int:
    stale_port = 8000 if expected_port != 8000 else 18001
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$name = 'ImmoApp Office Hub Front Door'; "
        "Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue "
        "| Remove-NetFirewallRule -ErrorAction Stop; "
        "New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow "
        f"-Protocol TCP -LocalPort {stale_port} -Profile Private | Out-Null"
    )
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return stale_port


@pytest.mark.hub_manager_docker_bootstrap
def test_installed_runtime_artifact_install_through_existing_hub() -> None:
    if os.environ.get("IMMOAPP_E2E_MANAGED_FRONT_DOOR_URL"):
        pytest.skip("Docker-backed artifact bootstrap is separate from managed-runtime E2E.")
    front_door_url = str(os.environ.get("IMMOAPP_E2E_FRONT_DOOR_URL", "")).rstrip("/")
    if not front_door_url:
        pytest.skip("IMMOAPP_E2E_FRONT_DOOR_URL is required for artifact bootstrap.")
    backend.ensure_front_door_ready(front_door_url)
    installed_exe = installed_hub_manager_path()
    assert_installed_build_identity(installed_exe)
    evidence_path = HUB_MANAGER_OUTPUT_DIR / "install-runtime-artifact.json"
    previous_mtime = prior_mtime_ns(evidence_path)

    with HubManagerAppDriver.launch_installed(installed_exe) as hub_manager:
        window = hub_manager.wait_for_main_window(timeout=60.0)
        hub_manager.wait_for_text(window, "Refresh status: GO", timeout=300.0)
        hub_manager.click_button(
            window,
            "Install Hub engine",
            automation_id="hubManagerAction_install-runtime-artifact",
        )
        confirmation = hub_manager.wait_for_window(title="Install Hub engine", timeout=20.0)
        hub_manager.click_button(confirmation, "Yes")
        login = hub_manager.wait_for_login(timeout=30.0)
        hub_manager.sign_in(login, username="owner", password="admin")
        evidence = wait_for_evidence(
            evidence_path,
            after_mtime_ns=previous_mtime,
            predicate=lambda payload: payload.get("runtime_artifact_status") == "GO"
            and payload.get("provider_config_valid") is True,
            timeout=900.0,
        )

    expected_commit = required_env_text("IMMOAPP_E2E_INSTALLED_SOURCE_COMMIT_SHA")
    artifact_inventory = read_json(Path(str(evidence["artifact_inventory_path"])))
    assert artifact_inventory["source_commit_sha"] == expected_commit
    assert evidence["packaged_payload_status"] == "GO"


def test_installed_runtime_artifact_reinstall(managed_hub_owner: ManagedOwner) -> None:
    installed_exe = installed_hub_manager_path()
    assert_installed_build_identity(installed_exe)
    evidence_path = HUB_MANAGER_OUTPUT_DIR / "install-runtime-artifact.json"
    previous_mtime = prior_mtime_ns(evidence_path)

    with HubManagerAppDriver.launch_installed(installed_exe) as hub_manager:
        window = hub_manager.wait_for_main_window(timeout=60.0)
        hub_manager.wait_for_text(window, "Refresh status: GO", timeout=300.0)
        hub_manager.click_button(
            window,
            "Install Hub engine",
            automation_id="hubManagerAction_install-runtime-artifact",
        )
        confirmation = hub_manager.wait_for_window(title="Install Hub engine", timeout=20.0)
        hub_manager.click_button(confirmation, "Yes")
        login = hub_manager.wait_for_login(timeout=30.0)
        hub_manager.sign_in(
            login,
            username=managed_hub_owner.username,
            password=managed_hub_owner.password,
        )
        evidence = wait_for_evidence(
            evidence_path,
            after_mtime_ns=previous_mtime,
            predicate=lambda payload: payload.get("runtime_artifact_status") == "GO"
            and payload.get("provider_config_valid") is True,
            timeout=900.0,
        )

    expected_commit = required_env_text("IMMOAPP_E2E_INSTALLED_SOURCE_COMMIT_SHA")
    artifact_inventory = read_json(Path(str(evidence["artifact_inventory_path"])))
    assert artifact_inventory["source_commit_sha"] == expected_commit
    assert evidence["packaged_payload_status"] == "GO"
    assert evidence["runtime_payload_update_status"] in {"GO", "not_required"}
    assert evidence["provider_registration_status"] == "GO"
    assert evidence["runtime_was_running"] is True
    assert evidence["runtime_restart_required"] is True
    assert evidence["runtime_restart_status"] == "GO"
    assert evidence["runtime_start_status"] == "GO"
    assert evidence["proof_result"] == "GO"
    wait_for_front_door(ready=True)
    owner = managed_user_by_email(managed_hub_owner.email)
    assert owner is not None
    assert owner["is_active"] is True


@pytest.mark.installed_hub_manager_elevated
def test_installed_finish_setup(managed_hub_owner: ManagedOwner) -> None:
    if not bool(ctypes.windll.shell32.IsUserAnAdmin()):
        pytest.fail("Finish-setup E2E must run from an already elevated interactive test runner.")

    installed_exe = installed_hub_manager_path()
    assert_installed_build_identity(installed_exe)
    front_door_url = required_env_text("IMMOAPP_E2E_MANAGED_FRONT_DOOR_URL")
    expected_port = urlparse(front_door_url).port
    assert expected_port is not None
    stale_port = _seed_stale_firewall_rule(expected_port=expected_port)
    assert stale_port != expected_port
    output = HUB_MANAGER_OUTPUT_DIR / "finish-hub-setup.json"
    previous_mtime = prior_mtime_ns(output)

    with HubManagerAppDriver.launch_installed(installed_exe) as hub_manager:
        window = hub_manager.wait_for_main_window(timeout=60.0)
        hub_manager.wait_for_text(window, "Refresh status: GO", timeout=300.0)
        hub_manager.click_button(
            window,
            "Finish setup",
            automation_id="hubManagerAction_finish-hub-setup",
        )
        confirmation = hub_manager.wait_for_window(title="Finish setup", timeout=20.0)
        hub_manager.click_button(confirmation, "Yes")
        login = hub_manager.wait_for_login(timeout=30.0)
        hub_manager.sign_in(
            login,
            username=managed_hub_owner.username,
            password=managed_hub_owner.password,
        )
        result = wait_for_evidence(
            output,
            after_mtime_ns=previous_mtime,
            predicate=lambda payload: payload.get("result") == "GO",
            timeout=600.0,
        )

    setup_evidence = read_json(Path(str(result["evidence_path"])))
    assert setup_evidence["proof_result"] == "GO"
    assert setup_evidence["foundation_applied_status"] == "GO"
    assert setup_evidence["hub_foundation_status"] == "GO"
    assert setup_evidence["elevated_setup_observed"] is True
    assert setup_evidence["firewall_status"] == "updated"
    assert setup_evidence["firewall"]["verified"] is True
    assert int(setup_evidence["firewall"]["local_port"]) == expected_port
    assert setup_evidence["firewall"]["reason_code"] == "firewall_rule_updated_and_verified"
    serialized = json.dumps(result)
    assert managed_hub_owner.password not in serialized
    assert "access_token" not in serialized.lower()
