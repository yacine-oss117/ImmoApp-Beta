from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver
from app.tests.e2e_desktop.installed_hub_manager_backend import (
    ManagedOwner,
    wait_for_front_door,
)
from app.tests.e2e_desktop.installed_hub_manager_test_support import (
    HUB_MANAGER_OUTPUT_DIR,
    assert_installed_build_identity,
    installed_hub_manager_path,
    prior_mtime_ns,
    sha256_file,
    wait_for_evidence,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.installed_hub_manager,
]


def _wait_action_evidence(action: str, *, after_mtime_ns: int) -> dict[str, object]:
    return wait_for_evidence(
        HUB_MANAGER_OUTPUT_DIR / f"{action}.json",
        after_mtime_ns=after_mtime_ns,
        predicate=lambda payload: payload.get("action") == action
        and payload.get("proof_result") == "GO",
    )


def _service_payload(wrapper_output: object) -> dict[str, object]:
    text = str(wrapper_output or "").strip()
    start = text.find("{")
    assert start >= 0
    payload = json.loads(text[start:])
    assert isinstance(payload, dict)
    return payload


def test_installed_managed_runtime_lifecycle(managed_hub_owner: ManagedOwner) -> None:
    installed_exe = installed_hub_manager_path()
    assert_installed_build_identity(installed_exe)
    wait_for_front_door(ready=True)

    with HubManagerAppDriver.launch_installed(installed_exe) as hub_manager:
        window = hub_manager.wait_for_main_window(timeout=60.0)
        hub_manager.wait_for_control_enabled(
            window,
            automation_id="hubManagerAction_status",
            timeout=300.0,
        )
        status_path = HUB_MANAGER_OUTPUT_DIR / "status.json"
        status_mtime = prior_mtime_ns(status_path)
        hub_manager.click_button(
            window,
            "Refresh status",
            automation_id="hubManagerAction_status",
        )
        _wait_action_evidence("status", after_mtime_ns=status_mtime)
        hub_manager.wait_for_text(window, "Ready", timeout=60.0)
        hub_manager.wait_for_control_enabled(
            window,
            automation_id="hubManagerAction_stop",
            timeout=300.0,
        )

        stop_path = HUB_MANAGER_OUTPUT_DIR / "stop.json"
        stop_mtime = prior_mtime_ns(stop_path)
        hub_manager.click_button(window, "Stop Hub", automation_id="hubManagerAction_stop")
        _wait_action_evidence("stop", after_mtime_ns=stop_mtime)
        wait_for_front_door(ready=False, timeout=120.0)
        hub_manager.wait_for_control_enabled(
            window,
            automation_id="hubManagerAction_start",
            timeout=300.0,
        )

        start_path = HUB_MANAGER_OUTPUT_DIR / "start.json"
        start_mtime = prior_mtime_ns(start_path)
        hub_manager.click_button(window, "Start Hub", automation_id="hubManagerAction_start")
        start = _wait_action_evidence("start", after_mtime_ns=start_mtime)
        assert start["runtime_command_status"] == "GO"
        assert start["service_status"] == "GO"
        assert start["front_door_health_status"] == "GO"
        wait_for_front_door(ready=True)
        hub_manager.wait_for_control_enabled(
            window,
            automation_id="hubManagerAction_health",
            timeout=300.0,
        )

        health_path = HUB_MANAGER_OUTPUT_DIR / "health.json"
        health_mtime = prior_mtime_ns(health_path)
        hub_manager.click_button(
            window,
            "Check connection",
            automation_id="hubManagerAction_health",
        )
        health = _wait_action_evidence("health", after_mtime_ns=health_mtime)
        assert health["front_door_health_status"] == "GO"
        hub_manager.wait_for_control_enabled(
            window,
            automation_id="hubManagerAction_logs",
            timeout=300.0,
        )
        hub_manager.scroll_main(window, direction="down")

        logs_path = HUB_MANAGER_OUTPUT_DIR / "logs.json"
        logs_mtime = prior_mtime_ns(logs_path)
        hub_manager.press_button(
            window,
            "Open logs",
            automation_id="hubManagerAction_logs",
        )
        login = hub_manager.wait_for_login(timeout=30.0)
        hub_manager.sign_in(
            login,
            username=managed_hub_owner.username,
            password=managed_hub_owner.password,
        )
        logs = _wait_action_evidence("logs", after_mtime_ns=logs_mtime)
        captured_logs = _service_payload(logs.get("wrapper_output"))
        assert captured_logs["logs_status"] == "GO"
        assert captured_logs["proof_result"] == "GO"
        assert str(captured_logs.get("logs") or "").strip()
        hub_manager.scroll_main(window, direction="up")
        hub_manager.wait_for_control_enabled(
            window,
            automation_id="hub-primary-action",
            timeout=300.0,
        )

        backup_path = HUB_MANAGER_OUTPUT_DIR / "backup-now.json"
        backup_mtime = prior_mtime_ns(backup_path)
        hub_manager.click_button(window, automation_id="hub-primary-action")
        confirmation = hub_manager.wait_for_window(title="Backup now", timeout=20.0)
        hub_manager.click_button(confirmation, "Yes")
        login = hub_manager.wait_for_login(timeout=30.0)
        hub_manager.sign_in(
            login,
            username=managed_hub_owner.username,
            password=managed_hub_owner.password,
        )
        backup = wait_for_evidence(
            backup_path,
            after_mtime_ns=backup_mtime,
            predicate=lambda payload: payload.get("action") == "backup"
            and payload.get("backup_status") == "GO"
            and payload.get("proof_result") == "GO",
            timeout=900.0,
        )
        archive = Path(str(backup["backup_bundle_path"]))
        assert archive.is_file()
        assert archive.stat().st_size == int(backup["backup_bundle_bytes"])
        assert sha256_file(archive) == backup["backup_bundle_sha256"]
        assert backup["database_dump_sha256"]
        hub_manager.wait_for_control_enabled(
            window,
            automation_id="hubManagerAction_restart",
            timeout=300.0,
        )

        restart_path = HUB_MANAGER_OUTPUT_DIR / "restart.json"
        restart_mtime = prior_mtime_ns(restart_path)
        hub_manager.click_button(window, "Restart Hub", automation_id="hubManagerAction_restart")
        restart = _wait_action_evidence("restart", after_mtime_ns=restart_mtime)
        assert restart["service_status"] == "GO"
        assert restart["front_door_health_status"] == "GO"
        wait_for_front_door(ready=True)
