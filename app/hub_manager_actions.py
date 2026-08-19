"""Command and action definitions for the installed Hub Manager app."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.hub_manager_access_client import (
    HubManagerAccessClientError,
    request_owner_authorization,
)
from core.contracts.hub_manager_authorization import (
    DELETE_HUB_DATA_ACTION,
    PROTECTED_ACTIONS,
)

HUB_MANAGER_SCRIPT_NAME = "hub_manager.ps1"
HUB_MANAGER_EXE_NAME = "ImmoApp Hub Manager.exe"
OWNER_AUTHORIZATION_EVIDENCE_NAME = "hub_owner_authorization.json"
DEFAULT_TIMEOUT_SECONDS = 180
LONG_TIMEOUT_SECONDS = 900
DEFAULT_LOG_RETENTION_DAYS = 14
DEFAULT_LOG_RETENTION_BYTES = 536_870_912
DELETE_HUB_DATA_AUTH_ACTION = DELETE_HUB_DATA_ACTION
PROTECTED_HUB_MANAGER_ACTIONS = frozenset(
    "delete-hub-data" if action == DELETE_HUB_DATA_ACTION else action
    for action in PROTECTED_ACTIONS
)


@dataclass(frozen=True)
class HubManagerAction:
    key: str
    label: str
    description: str
    group: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    needs_confirmation: bool = False
    use_windows_volumes: bool = False
    requires_owner_authorization: bool = False


@dataclass(frozen=True)
class HubManagerCommandResult:
    action: str
    exit_code: int
    stdout: str
    stderr: str
    output_json: Path
    payload: dict[str, Any] | None
    timed_out: bool
    error: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.error


ACTIONS: tuple[HubManagerAction, ...] = (
    HubManagerAction(
        "status",
        "Refresh status",
        "Read current Hub status and evidence.",
        "Status",
    ),
    HubManagerAction(
        "runtime-status",
        "Check Hub engine",
        "Check the installed Hub engine without starting anything.",
        "Status",
    ),
    HubManagerAction(
        "connection-details",
        "Connection details",
        "Show the Hub name and front-door connection details.",
        "Status",
    ),
    HubManagerAction(
        "firewall-status",
        "Check network access",
        "Check the private-network access rule for employee computers.",
        "Status",
    ),
    HubManagerAction(
        "start",
        "Start Hub",
        "Start the installed Hub runtime.",
        "Control",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
        use_windows_volumes=True,
    ),
    HubManagerAction(
        "stop",
        "Stop Hub",
        "Stop the installed Hub runtime.",
        "Control",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
        use_windows_volumes=True,
    ),
    HubManagerAction(
        "restart",
        "Restart Hub",
        "Restart the installed Hub runtime.",
        "Control",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
        use_windows_volumes=True,
    ),
    HubManagerAction(
        "health",
        "Check connection",
        "Check that employees can reach the Hub front door.",
        "Control",
    ),
    HubManagerAction(
        "finish-hub-setup",
        "Finish setup",
        "Finish the elevated Hub setup if installer elevation was declined.",
        "Setup",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
        needs_confirmation=True,
        requires_owner_authorization=True,
    ),
    HubManagerAction(
        "rename-hub",
        "Rename Hub",
        "Change the friendly Hub name shown to employees.",
        "Setup",
        requires_owner_authorization=True,
    ),
    HubManagerAction(
        "install-runtime-artifact",
        "Install Hub engine",
        "Install the bundled ImmoApp-managed Hub engine.",
        "Setup",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
        needs_confirmation=True,
        requires_owner_authorization=True,
    ),
    HubManagerAction(
        "cleanup-runtime-logs",
        "Clean Hub logs",
        "Apply bounded Hub log retention.",
        "Maintenance",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
        requires_owner_authorization=True,
    ),
    HubManagerAction(
        "delete-hub-data",
        "Danger Zone: delete Hub data",
        "Permanently delete local Hub state only after owner/admin approval and Windows admin elevation.",
        "Maintenance",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
        needs_confirmation=True,
        requires_owner_authorization=True,
    ),
    HubManagerAction(
        "backup-now",
        "Backup now",
        "Run an immediate release backup bundle.",
        "Maintenance",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
        needs_confirmation=True,
        requires_owner_authorization=True,
    ),
    HubManagerAction(
        "support",
        "Collect support file",
        "Collect redacted diagnostics for support.",
        "Maintenance",
        timeout_seconds=LONG_TIMEOUT_SECONDS,
    ),
    HubManagerAction(
        "logs",
        "Open logs",
        "Open or collect Hub logs through the managed runtime path.",
        "Maintenance",
        requires_owner_authorization=True,
    ),
    HubManagerAction(
        "copy-url",
        "Copy connection URL",
        "Copy the Hub front-door URL to the clipboard.",
        "Utilities",
    ),
    HubManagerAction(
        "open-desktop",
        "Open desktop app",
        "Open ImmoApp Desktop if it is installed on this computer.",
        "Utilities",
    ),
)

ACTION_BY_KEY = {action.key: action for action in ACTIONS}


def installed_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resolve_hub_manager_script(app_root: Path | None = None) -> Path:
    override = os.environ.get("IMMOAPP_HUB_MANAGER_SCRIPT")
    if override:
        return Path(override).resolve()
    root = app_root or installed_app_root()
    candidates = (
        root / "scripts" / HUB_MANAGER_SCRIPT_NAME,
        root.parent / "scripts" / HUB_MANAGER_SCRIPT_NAME,
        Path.cwd() / "scripts" / HUB_MANAGER_SCRIPT_NAME,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return (root / "scripts" / HUB_MANAGER_SCRIPT_NAME).resolve()


def resolve_powershell() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return str(candidate)
    return "powershell.exe"


def hub_manager_output_dir() -> Path:
    root = os.environ.get("IMMOAPP_APPDATA_ROOT")
    if root:
        base = Path(root)
    else:
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        base = Path(program_data) / "ImmoApp"
    output = base / "logs" / "hub-manager-app"
    output.mkdir(parents=True, exist_ok=True)
    return output


def action_output_json(action: str) -> Path:
    safe_action = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in action)
    return hub_manager_output_dir() / f"{safe_action}.json"


def owner_authorization_action_for_manager_action(action: str) -> str:
    if action == "delete-hub-data":
        return DELETE_HUB_DATA_AUTH_ACTION
    return action


def create_owner_authorization_evidence_file(
    username: str,
    password: str,
    *,
    base_url: str,
    action: str = DELETE_HUB_DATA_AUTH_ACTION,
) -> tuple[Path, dict[str, Any]]:
    """Request fresh Hub-issued evidence without persisting password or session tokens."""

    output = hub_manager_output_dir() / OWNER_AUTHORIZATION_EVIDENCE_NAME
    evidence_action = owner_authorization_action_for_manager_action(action)
    try:
        binding = _hub_binding()
        payload = request_owner_authorization(
            base_url=base_url,
            username=username,
            password=password,
            action=evidence_action,
            hub_binding=binding,
        )
    except (HubManagerAccessClientError, OSError, ValueError) as exc:
        reason_code = getattr(exc, "reason_code", "") or str(exc)
        if not reason_code:
            reason_code = "hub_owner_authorization_hub_state_unreadable"
        payload = {
            "kind": "immoapp_hub_owner_authorization_evidence",
            "schema_version": 3,
            "proof_result": "NO-GO",
            "owner_authorization_status": "NO-GO",
            "reason_code": str(reason_code),
            "action": evidence_action,
            "authorization_scope": "hub_manager_protected_action",
            "source": "hub_db",
            "plaintext_password_written": False,
            "session_token_written": False,
        }
    _write_private_json(output, payload)
    return output, payload


def _hub_binding() -> dict[str, str]:
    appdata_root = hub_manager_output_dir().parents[1]
    identity_path = appdata_root / "config" / "hub_identity.json"
    state_path = appdata_root / "config" / "hub_state_manifest.json"
    identity = load_json_payload(identity_path)
    state = load_json_payload(state_path)
    if identity is None or state is None:
        raise ValueError("hub_owner_authorization_hub_state_unreadable")
    hub_id = str(identity.get("hub_id") or "")
    if not hub_id or hub_id != str(state.get("hub_id") or ""):
        raise ValueError("hub_owner_authorization_hub_state_mismatch")
    return {
        "hub_id": hub_id,
        "hub_display_name": str(identity.get("hub_display_name") or ""),
        "hub_identity_sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest(),
        "hub_state_manifest_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "hub_state_install_lineage": str(state.get("install_lineage") or ""),
    }


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(temporary, path)


def build_hub_manager_command(
    *,
    action: str,
    script_path: Path,
    output_json: Path,
    hub_base_url: str = "",
    hub_display_name: str = "",
    use_windows_volumes: bool = False,
    confirm_runtime_artifact: bool = False,
    confirm_delete_hub_data: bool = False,
    typed_confirmation: str = "",
    owner_authorization_evidence_json: str = "",
    retention_days: int = DEFAULT_LOG_RETENTION_DAYS,
    max_total_bytes: int = DEFAULT_LOG_RETENTION_BYTES,
) -> list[str]:
    command = [
        resolve_powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-Action",
        action,
        "-OutputJson",
        str(output_json),
    ]
    if use_windows_volumes:
        command.append("-UseWindowsVolumes")
    if hub_base_url:
        command.extend(["-HubBaseUrl", hub_base_url])
    if hub_display_name:
        command.extend(["-HubDisplayName", hub_display_name])
    if confirm_runtime_artifact:
        command.append("-ConfirmInstallRuntimeArtifact")
    if confirm_delete_hub_data:
        command.append("-ConfirmDeleteHubData")
    if typed_confirmation:
        command.extend(["-TypedConfirmation", typed_confirmation])
    if owner_authorization_evidence_json:
        command.extend(["-OwnerAuthorizationEvidenceJson", owner_authorization_evidence_json])
    if action == "cleanup-runtime-logs":
        command.extend(
            [
                "-RetentionDays",
                str(retention_days),
                "-MaxTotalBytes",
                str(max_total_bytes),
            ]
        )
    return command


def load_json_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def hidden_child_process_kwargs() -> dict[str, Any]:
    """Prevent backend PowerShell actions from opening a console window."""

    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }
