from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea

from app import hub_manager_actions as actions_module
from app import hub_manager_app as module
from app.hub_manager_actions import (
    ACTION_BY_KEY,
    HUB_MANAGER_EXE_NAME,
    build_hub_manager_command,
    create_owner_authorization_evidence_file,
    hidden_child_process_kwargs,
    resolve_hub_manager_script,
)
from app.hub_manager_app import HubManagerCommandResult, HubManagerLoginDialog, HubManagerWindow
from app.hub_manager_owner_state import (
    OWNER_ACCOUNT_MISSING,
    OWNER_ACTIVATION_PENDING,
    OWNER_ACTIVE,
    HubOwnerState,
)
from app.hub_manager_status import normalize_hub_status
from app.hub_manager_style import HUB_MANAGER_STYLESHEET
from app.tests.e2e_desktop.hub_manager_control_coverage import (
    ACTION_REAL_EFFECT_TESTS,
    NON_ACTION_CONTROL_REAL_EFFECT_TESTS,
)

pytestmark = pytest.mark.ui


def test_hub_manager_app_wraps_installed_script_with_json_evidence(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "hub_manager.ps1"
    script.parent.mkdir()
    script.write_text("param()\n", encoding="utf-8")
    output = tmp_path / "evidence.json"

    command = build_hub_manager_command(
        action="start",
        script_path=script,
        output_json=output,
        use_windows_volumes=True,
    )

    assert command[:4] == [
        command[0],
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
    ]
    assert "-File" in command
    assert str(script) in command
    assert command[command.index("-Action") + 1] == "start"
    assert command[command.index("-OutputJson") + 1] == str(output)
    assert "-UseWindowsVolumes" in command


def test_hub_manager_app_exposes_artifact_not_candidate_install(tmp_path: Path) -> None:
    script = tmp_path / "hub_manager.ps1"
    script.write_text("param()\n", encoding="utf-8")
    output = tmp_path / "artifact.json"

    command = build_hub_manager_command(
        action="install-runtime-artifact",
        script_path=script,
        output_json=output,
        confirm_runtime_artifact=True,
    )

    assert "install-runtime-artifact" in ACTION_BY_KEY
    assert "install-runtime-candidate" not in ACTION_BY_KEY
    assert "-ConfirmInstallRuntimeArtifact" in command
    assert "-ConfirmInstallRuntimeCandidate" not in command
    assert HUB_MANAGER_EXE_NAME == "ImmoApp Hub Manager.exe"


def test_hub_manager_backend_actions_do_not_open_console_window() -> None:
    kwargs = hidden_child_process_kwargs()

    if os.name == "nt":
        assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
        startupinfo = kwargs["startupinfo"]
        assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
        assert startupinfo.wShowWindow == 0
    else:
        assert kwargs == {}


def test_owner_authorization_uses_hub_front_door_without_password_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    appdata = tmp_path / "ImmoApp"
    config = appdata / "config"
    config.mkdir(parents=True)
    (config / "hub_identity.json").write_text(
        '{"hub_id":"hub-1","hub_display_name":"Office"}', encoding="utf-8"
    )
    (config / "hub_state_manifest.json").write_text(
        '{"hub_id":"hub-1","install_lineage":"lineage-1"}', encoding="utf-8"
    )
    calls: list[dict[str, object]] = []

    def fake_request(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"proof_result": "GO", "evidence_nonce": "opaque-grant"}

    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(appdata))
    monkeypatch.setattr(actions_module, "request_owner_authorization", fake_request)

    path, payload = create_owner_authorization_evidence_file(
        "owner@example.test",
        "correct-password",
        base_url="http://127.0.0.1:18001",
        action="backup-now",
    )

    assert path == appdata / "logs" / "hub-manager-app" / "hub_owner_authorization.json"
    assert payload["proof_result"] == "GO"
    assert calls[0]["base_url"] == "http://127.0.0.1:18001"
    assert calls[0]["password"] == "correct-password"
    assert "correct-password" not in path.read_text(encoding="utf-8")


def test_hub_manager_script_resolution_prefers_app_scripts_folder(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "hub_manager.ps1"
    script.parent.mkdir()
    script.write_text("param()\n", encoding="utf-8")

    assert resolve_hub_manager_script(tmp_path) == script.resolve()


def test_hub_manager_script_resolution_allows_e2e_safe_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "fake_hub_manager.ps1"
    script.write_text("param()\n", encoding="utf-8")
    monkeypatch.setenv("IMMOAPP_HUB_MANAGER_SCRIPT", str(script))

    assert resolve_hub_manager_script() == script.resolve()


def _make_window(
    monkeypatch: pytest.MonkeyPatch,
    qapp: object,
    *,
    owner_state: HubOwnerState | None = None,
) -> HubManagerWindow:
    del qapp
    monkeypatch.setattr(module.QTimer, "singleShot", lambda *_args, **_kwargs: None)
    if owner_state is None:
        owner_state = HubOwnerState(
            state=OWNER_ACTIVE,
            setup_available=True,
            activation_available=False,
            reason_code="active_owner_admin_exists",
            active_owner_admin_count=1,
        )
    monkeypatch.setattr(module, "resolve_hub_owner_state", lambda _base_url: owner_state)
    window = HubManagerWindow()
    window._owner_state = owner_state
    return window


def test_hub_manager_dashboard_does_not_show_ready_without_runtime_and_front_door_go(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    window.update_summary(
        {
            "hub_display_name": "Main Office",
            "front_door_url": "http://10.10.10.10:8000",
            "hub_state_manifest_status": "GO",
            "runtime_artifact_status": "GO",
            "runtime_start_status": "NO-GO",
            "front_door_health_status": "NO-GO",
        }
    )

    assert window._readiness.text() == "Needs setup"
    assert window._hero_status.text() == "Needs setup"
    assert window._runtime.text() == "Hub not started"
    assert window._hero_title.text() == "Main Office Hub"
    assert window._primary_action_key == "start"
    assert window._primary_action_button.text() == "Start Hub"
    assert "10.10.10.10" not in window._front_door.text()
    assert "[ ] Hub started" in window._checklist.text()
    assert "[ ] Employee connection verified" in window._checklist.text()


def test_hub_manager_dashboard_ready_requires_runtime_and_front_door_go(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    window.update_summary(
        {
            "hub_display_name": "Main Office",
            "runtime_artifact_status": "GO",
            "runtime_start_status": "GO",
            "front_door_health_status": "GO",
            "firewall_status": "already_present_valid",
            "backup_status": "GO",
            "lan_workstation_status": "GO",
        }
    )

    assert window._readiness.text() == "Ready"
    assert window._hero_status.text() == "Ready"
    assert window._runtime.text() == "Ready"
    assert window._primary_action_key == "backup-now"
    assert window._primary_action_button.text() == "Backup now"
    assert "Employees can connect" in window._hero_subtitle.text()
    assert "[OK] Hub started" in window._checklist.text()
    assert "[OK] Employee connection verified" in window._checklist.text()


def test_hub_manager_login_gate_accepts_active_owner_admin(
    monkeypatch: pytest.MonkeyPatch, qapp: object, tmp_path: Path
) -> None:
    del qapp
    calls: list[tuple[str, str, str]] = []
    evidence_path = tmp_path / "owner-authorization.json"

    def fake_authorize(
        username: str, password: str, *, base_url: str, action: str
    ) -> tuple[Path, dict[str, str]]:
        assert base_url == "http://127.0.0.1:18001"
        calls.append((username, password, action))
        evidence_path.write_text('{"proof_result":"GO"}', encoding="utf-8")
        return evidence_path, {"proof_result": "GO"}

    monkeypatch.setattr(module, "create_owner_authorization_evidence_file", fake_authorize)
    dialog = HubManagerLoginDialog(
        hub_base_url="http://127.0.0.1:18001",
        authorization_action="backup-now",
    )
    dialog._username.setText("owner@example.test")
    dialog._password.setText("correct-password")

    dialog._attempt_login()

    assert calls == [("owner@example.test", "correct-password", "backup-now")]
    assert dialog.result() == int(module.QDialog.DialogCode.Accepted)
    assert dialog.authorization_evidence_path == evidence_path
    assert dialog._username.text() == ""
    assert dialog._password.text() == ""


def test_hub_manager_login_gate_rejects_employee_inactive_or_wrong_password(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    del qapp

    def fake_authorize(
        username: str, password: str, *, base_url: str, action: str
    ) -> tuple[Path, dict[str, str]]:
        del username, password, base_url, action
        return Path("evidence.json"), {
            "proof_result": "NO-GO",
            "reason_code": "hub_owner_authorization_role_not_allowed",
        }

    monkeypatch.setattr(module, "create_owner_authorization_evidence_file", fake_authorize)
    dialog = HubManagerLoginDialog(
        hub_base_url="http://127.0.0.1:18001",
        authorization_action="cleanup-runtime-logs",
    )
    dialog._username.setText("employee@example.test")
    dialog._password.setText("wrong-or-employee-password")

    dialog._attempt_login()

    assert dialog.result() == 0
    assert dialog.authorization_evidence_path is None
    assert dialog._password.text() == ""
    assert "owner/admin account" in dialog._status.text()


def test_hub_manager_dashboard_shows_create_owner_when_missing(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    owner_state = HubOwnerState(
        state=OWNER_ACCOUNT_MISSING,
        setup_available=True,
        activation_available=False,
        reason_code="owner_account_missing",
    )
    window = _make_window(monkeypatch, qapp, owner_state=owner_state)

    window.update_summary({"front_door_url": "http://10.10.10.10:8000"})

    visible_text = "\n".join(
        [
            window._owner_setup_status.text(),
            window._owner_setup_message.text(),
            window._hero_subtitle.text(),
            window._primary_action_button.text(),
            window._checklist.text(),
        ]
    )
    assert "Create owner account" in visible_text
    assert "Activate owner account" not in visible_text
    assert window._checklist.text().splitlines()[0] == "[ ] Create owner account"
    assert window._primary_action_key == "owner-register"
    assert window._primary_action_button.text() == "Create owner account"
    assert not window._create_owner_button.isHidden()
    assert window._activate_owner_button.isHidden()


def test_hub_manager_dashboard_shows_setup_unavailable_without_platform_approval(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    owner_state = HubOwnerState(
        state=OWNER_ACCOUNT_MISSING,
        setup_available=False,
        activation_available=False,
        reason_code="platform_admin_email_missing",
    )
    window = _make_window(monkeypatch, qapp, owner_state=owner_state)

    window.update_summary({"front_door_url": "http://10.10.10.10:8000"})

    assert window._checklist.text().splitlines()[0] == "[ ] Owner setup available"
    assert "Owner setup is unavailable" in window._owner_setup_status.text()
    assert "Platform approval email is not configured" in window._owner_setup_message.text()
    assert window._create_owner_button.isHidden()
    assert window._activate_owner_button.isHidden()


def test_hub_manager_dashboard_explains_unreachable_owner_state(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    owner_state = HubOwnerState(
        state=OWNER_ACCOUNT_MISSING,
        setup_available=False,
        activation_available=False,
        reason_code="hub_owner_authorization_unreachable",
    )
    window = _make_window(monkeypatch, qapp, owner_state=owner_state)

    window.update_summary({})

    assert window._checklist.text().splitlines()[0] == "[ ] Owner setup status loaded"
    assert "Owner setup status is unavailable" in window._owner_setup_status.text()
    assert "Start or check the Hub" in window._owner_setup_message.text()
    assert "Platform approval email" not in window._owner_setup_message.text()
    assert window._primary_action_key == "start"
    assert window._primary_action_button.text() == "Start Hub"
    assert window._create_owner_button.isHidden()
    assert window._activate_owner_button.isHidden()


def test_hub_manager_dashboard_shows_activate_owner_when_approved_inactive(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    owner_state = HubOwnerState(
        state=OWNER_ACTIVATION_PENDING,
        setup_available=True,
        activation_available=True,
        reason_code="approved_inactive_owner_exists",
        inactive_owner_count=1,
    )
    window = _make_window(monkeypatch, qapp, owner_state=owner_state)

    window.update_summary({"front_door_url": "http://10.10.10.10:8000"})

    assert window._checklist.text().splitlines()[0] == "[ ] Activate owner account"
    assert window._primary_action_key == "owner-activate"
    assert window._primary_action_button.text() == "Activate owner account"
    assert window._create_owner_button.isHidden()
    assert not window._activate_owner_button.isHidden()


def test_hub_manager_dashboard_shows_waiting_copy_for_pending_registration(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    owner_state = HubOwnerState(
        state=OWNER_ACTIVATION_PENDING,
        setup_available=True,
        activation_available=False,
        reason_code="registration_pending_platform_approval",
        pending_registration_count=1,
    )
    window = _make_window(monkeypatch, qapp, owner_state=owner_state)

    window.update_summary({"front_door_url": "http://10.10.10.10:8000"})

    assert window._checklist.text().splitlines()[0] == "[ ] Owner request approved"
    assert "waiting for approval" in window._owner_setup_status.text()
    assert "platform admin" in window._owner_setup_message.text()
    assert window._create_owner_button.isHidden()
    assert window._activate_owner_button.isHidden()


def test_hub_manager_dashboard_can_open_without_owner_login(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    window.update_summary({"front_door_url": "http://10.10.10.10:8000"})

    checklist = window._checklist.text().splitlines()
    assert checklist[0] == "[OK] Owner account active"
    assert checklist[1] == "[ ] Hub identity saved"
    assert window._action_buttons["status"].isEnabled()
    assert window._action_buttons["support"].isEnabled()


def test_non_status_evidence_preserves_loaded_runtime_state_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    qapp: object,
    tmp_path: Path,
) -> None:
    window = _make_window(monkeypatch, qapp)
    window.update_summary(
        {
            "hub_display_name": "Main Office",
            "front_door_url": "http://127.0.0.1:18001",
            "runtime_artifact_status": "GO",
            "runtime_start_status": "GO",
            "front_door_health_status": "GO",
        }
    )

    window.on_action_completed(
        HubManagerCommandResult(
            action="cleanup-runtime-logs",
            exit_code=0,
            stdout="",
            stderr="",
            output_json=tmp_path / "cleanup.json",
            payload={"proof_result": "GO", "deleted_file_count": 2},
            timed_out=False,
            error="",
        )
    )

    assert not hasattr(window, "_owner_username")
    assert not hasattr(window, "_owner_password")
    assert window._readiness.text() == "Ready"


def test_hub_manager_uses_nested_runtime_detection_as_live_truth(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    window.update_summary(
        {
            "runtime_detection": {
                "runtime_artifact_status": "GO",
                "runtime_start_status": "GO",
                "front_door_live_probe": {
                    "front_door_url": "http://127.0.0.1:8000",
                    "front_door_health_status": "GO",
                    "health_status": 200,
                },
                "provider": {
                    # Provider files can contain stale registration-time fields; fresh detection wins.
                    "runtime_start_status": "NO-GO",
                },
            },
        }
    )

    assert window._readiness.text() == "Ready"
    assert window._runtime.text() == "Ready"
    assert window._primary_action_key == "backup-now"
    assert window._primary_action_button.text() == "Backup now"
    assert "Install Hub engine" not in window._next_action.text()
    assert "[OK] Hub engine installed" in window._checklist.text()
    assert "[OK] Hub started" in window._checklist.text()
    assert "[OK] Employee connection verified" in window._checklist.text()


def test_hub_status_normalizer_prefers_fresh_detection_over_provider() -> None:
    status = normalize_hub_status(
        {
            "runtime_detection": {
                "runtime_artifact_status": "GO",
                "runtime_start_status": "GO",
                "front_door_live_probe": {
                    "front_door_url": "http://127.0.0.1:8000",
                    "front_door_health_status": "GO",
                },
                "provider": {
                    "runtime_artifact_status": "GO",
                    "runtime_start_status": "NO-GO",
                },
            },
        }
    )

    assert status.runtime_artifact_ok
    assert status.runtime_start_ok
    assert status.front_door_ok
    assert status.ready


def test_hub_status_normalizer_accepts_status_collector_front_door_schema() -> None:
    status = normalize_hub_status(
        {
            "hub_base_url": "http://127.0.0.1:18001",
            "hub_address": {"front_door_url": "http://127.0.0.1:18001"},
        }
    )

    assert status.front_door == "http://127.0.0.1:18001"


def test_hub_status_normalizer_accepts_fresh_managed_runtime_evidence() -> None:
    status = normalize_hub_status(
        {
            "action": "status",
            "runtime_detection": {"runtime_artifact_status": "GO"},
            "runtime_command_status": "GO",
            "service_status": "GO",
            "compose_service_status": "GO",
            "front_door_health_status": "GO",
            "health_status": 200,
            "proof_result": "GO",
        }
    )

    assert status.runtime_artifact_ok
    assert status.runtime_start_ok
    assert status.front_door_ok
    assert status.ready


def test_hub_status_normalizer_rejects_managed_runtime_no_go() -> None:
    status = normalize_hub_status(
        {
            "action": "status",
            "runtime_detection": {"runtime_artifact_status": "GO"},
            "runtime_command_status": "GO",
            "service_status": "GO",
            "front_door_health_status": "GO",
            "health_status": 200,
            "proof_result": "NO-GO",
        }
    )

    assert not status.runtime_start_ok
    assert not status.front_door_ok
    assert not status.ready


def test_hub_manager_does_not_treat_raw_front_door_as_employee_connection(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    window.update_summary(
        {
            "front_door_url": "http://127.0.0.1:8000",
            "front_door_health_status": "GO",
            "health_status": 200,
            "runtime_artifact_status": "NO-GO",
            "runtime_start_status": "NO-GO",
        }
    )

    assert window._readiness.text() == "Needs setup"
    assert window._runtime.text() == "Runtime missing"
    assert "[ ] Hub engine installed" in window._checklist.text()
    assert "[ ] Hub started" in window._checklist.text()
    assert "[ ] Employee connection verified" in window._checklist.text()
    assert "Hub must be running" in window._network_summary.text()


def test_hub_manager_default_copy_is_customer_facing(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)
    window.update_summary(
        {
            "hub_display_name": "Main Office",
            "front_door_url": "http://10.10.10.10:8000",
            "runtime_artifact_status": "GO",
            "runtime_start_status": "NO-GO",
            "front_door_health_status": "NO-GO",
        }
    )

    default_copy = "\n".join(
        [
            window._hero_subtitle.text(),
            window._front_door.text(),
            window._next_action.text(),
            window._checklist.text(),
            window._network_summary.text(),
            window._backup_restore.text(),
        ]
    ).lower()

    assert "10.10.10.10" not in default_copy
    assert "front-door" not in default_copy
    assert "runtime" not in default_copy
    assert "proof" not in default_copy
    assert "employee connection" in default_copy


def test_hub_manager_hides_technical_details_by_default(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    assert window._technical_group.isHidden()
    assert window._technical_toggle.text() == "Show technical details"

    window.toggle_technical_details()

    assert not window._technical_group.isHidden()
    assert window._technical_toggle.text() == "Hide technical details"


def test_hub_manager_uses_whole_page_scroll_and_separate_status_widgets(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)
    scroll = cast(QScrollArea, window.centralWidget())

    assert isinstance(scroll, QScrollArea)
    assert scroll.widgetResizable()
    assert window._hero_status is not window._readiness
    assert window._hero_status.parent() is not window._readiness.parent()


def test_hub_manager_buttons_have_click_affordance(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    assert "QPushButton:hover" in HUB_MANAGER_STYLESHEET
    assert "QPushButton:pressed" in HUB_MANAGER_STYLESHEET
    assert "QPushButton:focus" in HUB_MANAGER_STYLESHEET
    assert window._primary_action_button.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert window._secondary_action_button.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert window._technical_toggle.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert all(
        button.cursor().shape() == Qt.CursorShape.PointingHandCursor
        for button in window._action_buttons.values()
    )


def test_hub_manager_exposes_every_action_as_a_button(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    assert set(window._action_buttons) == set(ACTION_BY_KEY)
    for key, button in window._action_buttons.items():
        assert button.objectName() == f"hubManagerAction_{key}"
        assert button.toolTip() == ACTION_BY_KEY[key].description


def test_hub_manager_primary_button_runs_current_recommended_action(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)
    clicked: list[str] = []
    monkeypatch.setattr(window, "run_action", clicked.append)
    window.update_summary(
        {
            "hub_display_name": "Main Office",
            "runtime_artifact_status": "GO",
            "runtime_start_status": "NO-GO",
            "front_door_health_status": "NO-GO",
        }
    )

    window._primary_action_button.click()

    assert clicked == ["start"]


def test_hub_manager_uses_existing_owner_setup_dialogs() -> None:
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "from app.widgets.register_dialog import RegisterDialog" in source
    assert "from app.widgets.activate_dialog import ActivateDialog" in source
    assert "open_owner_registration" in source
    assert "open_owner_activation" in source


def test_hub_manager_owner_setup_buttons_open_existing_dialogs_with_hub_url(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    owner_state = HubOwnerState(
        state=OWNER_ACCOUNT_MISSING,
        setup_available=True,
        activation_available=False,
        reason_code="owner_account_missing",
    )
    window = _make_window(monkeypatch, qapp, owner_state=owner_state)
    config_calls: list[dict[str, object]] = []
    opened: list[str] = []

    class FakeDialog:
        def __init__(self, name: str) -> None:
            self._name = name

        def exec(self) -> int:
            opened.append(self._name)
            return 0

    monkeypatch.setattr(module, "set_api_config", lambda **kwargs: config_calls.append(kwargs))
    monkeypatch.setattr(module, "create_register_dialog", lambda _parent: FakeDialog("register"))
    monkeypatch.setattr(module, "create_activate_dialog", lambda _parent: FakeDialog("activate"))

    window.update_summary(
        {
            "hub_display_name": "Main Office",
            "front_door_url": "http://127.0.0.1:18001",
        }
    )
    window.open_owner_registration()
    window._owner_state = HubOwnerState(
        state=OWNER_ACTIVATION_PENDING,
        setup_available=True,
        activation_available=True,
        reason_code="approved_inactive_owner_exists",
    )
    window.open_owner_activation()

    assert opened == ["register", "activate"]
    assert config_calls
    assert config_calls[0]["base_url"] == "http://127.0.0.1:18001"
    assert config_calls[0]["connection_source"] == "local_hub"
    assert config_calls[0]["hub_display_name"] == "Main Office"


def test_hub_manager_protected_action_stops_before_login_without_active_owner(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    owner_state = HubOwnerState(
        state=OWNER_ACCOUNT_MISSING,
        setup_available=True,
        activation_available=False,
        reason_code="owner_account_missing",
    )
    window = _make_window(monkeypatch, qapp, owner_state=owner_state)
    started: list[bool] = []
    messages: list[str] = []

    class LoginShouldNotOpen:
        def __init__(self) -> None:
            raise AssertionError("login dialog should not open without an active owner")

    monkeypatch.setattr(module, "HubManagerLoginDialog", LoginShouldNotOpen)
    monkeypatch.setattr(module.HubManagerWorker, "start", lambda _self: started.append(True))
    monkeypatch.setattr(
        module.QMessageBox,
        "information",
        lambda _parent, _title, message: messages.append(message),
    )
    window.update_summary({"front_door_url": "http://10.10.10.10:8000"})

    window.run_action("backup-now")

    assert started == []
    assert messages == [
        "Create and activate the Hub owner account before using protected Hub Manager actions."
    ]


def test_hub_manager_protected_action_does_not_execute_without_login_credentials(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)
    started: list[bool] = []

    class RejectedLogin:
        authorization_evidence_path = None

        def __init__(self, *, hub_base_url: str, authorization_action: str) -> None:
            assert hub_base_url == "http://127.0.0.1:18001"
            assert authorization_action == "cleanup-runtime-logs"

        def exec(self) -> module.QDialog.DialogCode:
            return module.QDialog.DialogCode.Rejected

    monkeypatch.setattr(module, "HubManagerLoginDialog", RejectedLogin)
    monkeypatch.setattr(module.HubManagerWorker, "start", lambda _self: started.append(True))
    window.update_summary({"front_door_url": "http://127.0.0.1:18001"})

    window.run_action("cleanup-runtime-logs")

    assert started == []


def test_hub_manager_protected_action_uses_owner_login_dialog(
    monkeypatch: pytest.MonkeyPatch, qapp: object, tmp_path: Path
) -> None:
    window = _make_window(monkeypatch, qapp)
    started: list[module.HubManagerWorker] = []
    evidence_path = tmp_path / "owner-authorization.json"
    evidence_path.write_text('{"proof_result":"GO"}', encoding="utf-8")

    class AcceptedLogin:
        authorization_evidence_path = evidence_path

        def __init__(self, *, hub_base_url: str, authorization_action: str) -> None:
            assert hub_base_url == "http://127.0.0.1:18001"
            assert authorization_action == "cleanup-runtime-logs"

        def exec(self) -> module.QDialog.DialogCode:
            return module.QDialog.DialogCode.Accepted

    monkeypatch.setattr(module, "HubManagerLoginDialog", AcceptedLogin)
    monkeypatch.setattr(module.HubManagerWorker, "start", lambda self: started.append(self))
    window.update_summary({"front_door_url": "http://127.0.0.1:18001"})

    window.run_action("cleanup-runtime-logs")

    assert len(started) == 1
    assert started[0]._owner_authorization_evidence_path == evidence_path
    assert not hasattr(window, "_owner_username")
    assert not hasattr(window, "_owner_password")


def test_hub_manager_danger_zone_is_gated_phase_two_action(
    monkeypatch: pytest.MonkeyPatch, qapp: object
) -> None:
    window = _make_window(monkeypatch, qapp)

    assert "delete-hub-data" in ACTION_BY_KEY
    assert ACTION_BY_KEY["delete-hub-data"].requires_owner_authorization
    assert ACTION_BY_KEY["backup-now"].requires_owner_authorization
    assert ACTION_BY_KEY["logs"].requires_owner_authorization
    assert not ACTION_BY_KEY["status"].requires_owner_authorization
    assert not ACTION_BY_KEY["support"].requires_owner_authorization
    assert window._worker is None
    assert "agency owner/admin login" in window._danger_zone.text()
    assert "Windows administrator approval" in window._danger_zone.text()
    assert "Uninstall keeps Hub data by default" in window._danger_zone.text()
    assert "DELETE HUB DATA" in window._danger_zone.text()
    assert (
        create_owner_authorization_evidence_file.__name__ in module.HubManagerWorker.run.__globals__
    )
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "Owner/admin email or username" in source
    assert "QLineEdit.EchoMode.Password" in source
    assert "Path to agency owner/admin authorization evidence JSON" not in source


def test_every_hub_manager_control_is_assigned_to_a_real_effect_e2e_journey() -> None:
    assert set(ACTION_REAL_EFFECT_TESTS) == set(ACTION_BY_KEY)
    assert all("::test_" in node_id for node_id in ACTION_REAL_EFFECT_TESTS.values())
    assert set(NON_ACTION_CONTROL_REAL_EFFECT_TESTS) == {
        "create-owner",
        "activate-owner",
        "primary-action",
        "secondary-action",
        "technical-details",
        "open-evidence-folder",
    }
