from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, cast

import pytest

from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.installed_hub_manager,
]


def _required_env_path(name: str) -> Path:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        pytest.skip(f"{name} is required for installed Hub Manager E2E.")
    path = Path(raw).resolve()
    if not path.exists():
        pytest.fail(f"{name} does not exist: {path}")
    return path


def _required_env_text(name: str) -> str:
    value = str(os.environ.get(name, "") or "").strip()
    if not value:
        pytest.skip(f"{name} is required for installed Hub Manager E2E.")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def _wait_for_protected_gate(hub_manager: HubManagerAppDriver, window: object) -> str:
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        if hub_manager.find_window(automation_id="hubManagerLoginDialog") is not None:
            return "login"
        visible_text = hub_manager.window_text(window)
        if (
            "Owner account required" in visible_text
            and "Create and activate the Hub owner account" in visible_text
        ):
            return "owner_required"
        time.sleep(0.25)
    raise AssertionError("Installed Hub Manager did not gate protected action.")


def test_installed_hub_manager_runs_safe_status_and_gates_protected_actions() -> None:
    installed_exe = _required_env_path("IMMOAPP_E2E_INSTALLED_HUB_MANAGER_PATH")
    expected_source_commit = _required_env_text("IMMOAPP_E2E_INSTALLED_SOURCE_COMMIT_SHA")
    install_root = installed_exe.parent

    build_identity = _read_json(install_root / "_internal" / "app" / "build_identity.json")
    assert build_identity["git_sha"] == expected_source_commit
    assert (install_root / "scripts" / "hub_manager.ps1").is_file()
    assert (install_root / "scripts" / "hub_manager_authorization.ps1").is_file()
    assert (install_root / "scripts" / "common.ps1").is_file()

    protected_output = Path(
        r"C:\ProgramData\ImmoApp\logs\hub-manager-app\cleanup-runtime-logs.json"
    )
    protected_output_mtime = protected_output.stat().st_mtime if protected_output.exists() else None

    with HubManagerAppDriver.launch_installed(installed_exe) as hub_manager:
        window = hub_manager.wait_for_main_window(timeout=45.0)
        hub_manager.wait_for_text(window, "Office Hub", timeout=15.0)

        hub_manager.click_button(window, "Refresh status", automation_id="hubManagerAction_status")
        hub_manager.wait_for_action_text(window, "Refresh status: GO", timeout=220.0)
        hub_manager.wait_for_text(window, "[OK] Hub engine installed", timeout=10.0)

        hub_manager.click_button(
            window,
            "Connection details",
            automation_id="hubManagerAction_connection-details",
        )
        hub_manager.wait_for_action_text(window, "Connection details: GO", timeout=90.0)

        hub_manager.click_button(
            window,
            "Clean Hub logs",
            automation_id="hubManagerAction_cleanup-runtime-logs",
        )
        gate = _wait_for_protected_gate(hub_manager, window)
        assert gate in {"login", "owner_required"}

        if gate == "owner_required":
            hub_manager.wait_for_text(
                window,
                "Create and activate the Hub owner account",
                timeout=10.0,
            )
            hub_manager.click_button(window, "OK")

        visible_text = hub_manager.window_text(window)
        assert "Clean Hub logs: GO" not in visible_text

    if protected_output_mtime is None:
        assert not protected_output.exists()
    else:
        assert protected_output.exists()
        assert protected_output.stat().st_mtime == protected_output_mtime
