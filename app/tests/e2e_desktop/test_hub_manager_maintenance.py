from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver, load_json

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.hub_manager_maintenance,
]

_PROGRAMDATA_ROOT = Path(r"C:\ProgramData\ImmoApp")
_IDENTITY_PATH = _PROGRAMDATA_ROOT / "config" / "hub_identity.json"
_STATE_PATH = _PROGRAMDATA_ROOT / "config" / "hub_state_manifest.json"
_AUTHORIZATION_PATH = (
    _PROGRAMDATA_ROOT / "logs" / "hub-manager-app" / "hub_owner_authorization.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def _wait_for_hub_name(expected: str, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _IDENTITY_PATH.is_file() and _STATE_PATH.is_file():
            identity = _read_json(_IDENTITY_PATH)
            state = _read_json(_STATE_PATH)
            if (
                identity.get("hub_display_name") == expected
                and state.get("hub_display_name") == expected
            ):
                return
        time.sleep(0.25)
    raise AssertionError(f"Hub identity and state were not renamed to {expected!r}.")


def _wait_for_json(path: Path, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return load_json(path)
        time.sleep(0.25)
    raise AssertionError(f"Hub Manager evidence was not written: {path}")


def test_owner_maintenance_controls_execute_real_effects(
    repo_root: Path,
    e2e_client_python: Path,
) -> None:
    assert _IDENTITY_PATH.is_file()
    assert _STATE_PATH.is_file()
    preserved = {
        _IDENTITY_PATH: _IDENTITY_PATH.read_bytes(),
        _STATE_PATH: _STATE_PATH.read_bytes(),
    }
    managed_logs = _PROGRAMDATA_ROOT / "logs" / "managed-runtime"
    managed_logs.mkdir(parents=True, exist_ok=True)
    expired_log = managed_logs / f"hub-manager-e2e-expired-{uuid.uuid4().hex}.log"
    expired_log.write_text("expired log evidence", encoding="utf-8")
    expired_at = time.time() - (30 * 24 * 60 * 60)
    os.utime(expired_log, (expired_at, expired_at))
    renamed_hub = f"E2E Office {uuid.uuid4().hex[:8]}"
    rename_evidence_path = _PROGRAMDATA_ROOT / "logs" / "hub-manager-app" / "rename-hub.json"
    rename_evidence_path.unlink(missing_ok=True)

    try:
        with HubManagerAppDriver.launch(repo_root, e2e_client_python) as hub_manager:
            window = hub_manager.wait_for_main_window()
            hub_manager.wait_for_text(window, "Refresh status: GO", timeout=220.0)

            hub_manager.click_button(
                window,
                "Clean Hub logs",
                automation_id="hubManagerAction_cleanup-runtime-logs",
            )
            login = hub_manager.wait_for_login()
            hub_manager.sign_in_owner(login)
            hub_manager.wait_for_action_text(window, "Clean Hub logs: GO", timeout=120.0)

            cleanup = load_json(
                _PROGRAMDATA_ROOT / "logs" / "hub-manager-app" / "cleanup-runtime-logs.json"
            )
            assert cleanup["kind"] == "immoapp_managed_runtime_log_retention_evidence"
            assert cleanup["proof_result"] == "GO"
            assert cleanup["deleted_file_count"] >= 1
            assert not expired_log.exists()

            hub_manager.click_button(
                window,
                "Rename Hub",
                automation_id="hubManagerAction_rename-hub",
            )
            rename_dialog = hub_manager.wait_for_window(title="Rename Hub", timeout=20.0)
            hub_manager.set_first_edit_text(rename_dialog, renamed_hub)
            hub_manager.click_button(rename_dialog, "OK")
            login = hub_manager.wait_for_login()
            hub_manager.sign_in_owner(login)
            _wait_for_hub_name(renamed_hub)

            rename_evidence = _wait_for_json(rename_evidence_path)
            assert rename_evidence["kind"] == "immoapp_hub_identity_evidence"
            assert rename_evidence["proof_result"] == "GO"
            assert rename_evidence["hub_display_name"] == renamed_hub
            hub_manager.wait_for_text(window, f"{renamed_hub} Hub", timeout=220.0)

            deadline = time.monotonic() + 10.0
            while _AUTHORIZATION_PATH.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            assert not _AUTHORIZATION_PATH.exists()
    finally:
        expired_log.unlink(missing_ok=True)
        for path, content in preserved.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
