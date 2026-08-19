from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
import requests

from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_smoke,
    pytest.mark.hub_manager_delete_data,
]


def _run_powershell(
    repo_root: Path,
    args: list[str],
    *,
    env: dict[str, str],
    timeout: int = 120,
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


def _disposable_hub_env(programdata: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
            "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
            "IMMOAPP_SKIP_CELERY_APP": "1",
            "PGCONNECT_TIMEOUT": "5",
        }
    )
    return env


def _setup_disposable_hub(repo_root: Path, programdata: Path, env: dict[str, str]) -> None:
    output = programdata / "logs" / "hub_setup.json"
    result = _run_powershell(
        repo_root,
        [
            "-File",
            str(repo_root / "scripts" / "setup_office_hub.ps1"),
            "-DataRoot",
            str(programdata),
            "-HubDisplayName",
            "E2E Disposable Hub",
            "-NoLanAccess",
            "-NoAutoStart",
            "-NoStartHub",
            "-NoShortcuts",
            "-OutputJson",
            str(output),
        ],
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = _read_json(output)
    assert payload["proof_result"] == "GO"
    for relative in (
        "config/delete-target.txt",
        "data/delete-target.txt",
        "runtime/delete-target.txt",
    ):
        target = programdata / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("delete me", encoding="utf-8")


def _create_owner_delete_evidence(
    repo_root: Path,
    programdata: Path,
    *,
    base_url: str,
    password: str,
    env: dict[str, str],
) -> tuple[Path, dict[str, Any], subprocess.CompletedProcess[str]]:
    output = programdata / "logs" / "owner_delete_authorization.json"
    command = [
        sys.executable,
        str(repo_root / "scripts" / "create_hub_owner_authorization_evidence.py"),
        "--username",
        "owner",
        "--password-stdin",
        "--action",
        "delete_hub_data",
        "--base-url",
        base_url,
        "--hub-identity-json",
        str(programdata / "config" / "hub_identity.json"),
        "--hub-state-manifest-json",
        str(programdata / "config" / "hub_state_manifest.json"),
        "--output-json",
        str(output),
    ]
    assert password not in command
    result = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        input=password,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        check=False,
    )
    assert output.is_file()
    return output, _read_json(output), result


def _run_delete_hub_data(
    repo_root: Path,
    programdata: Path,
    evidence: Path,
    *,
    base_url: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    output = programdata / "logs" / "delete_hub_data.json"
    return _run_powershell(
        repo_root,
        [
            "-File",
            str(repo_root / "scripts" / "hub_manager.ps1"),
            "-Action",
            "delete-hub-data",
            "-ConfirmDeleteHubData",
            "-TypedConfirmation",
            "DELETE HUB DATA",
            "-OwnerAuthorizationEvidenceJson",
            str(evidence),
            "-HubBaseUrl",
            base_url,
            "-OutputJson",
            str(output),
        ],
        env={**env, "IMMOAPP_TEST_ASSUME_WINDOWS_ADMIN": "1"},
        timeout=180,
    )


def _wait_for_delete_evidence(path: Path, timeout: float = 180.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if path.is_file():
            last_payload = _read_json(path)
            if last_payload.get("reason_code") == "hub_data_deleted":
                return last_payload
        time.sleep(0.25)
    raise AssertionError(f"Hub data deletion did not reach GO. Last evidence: {last_payload}")


def test_ui_deletes_disposable_hub_data(
    repo_root: Path,
    e2e_front_door_url: str,
    e2e_client_python: Path,
    tmp_path: Path,
) -> None:
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    env = _disposable_hub_env(programdata)
    _setup_disposable_hub(repo_root, programdata, env)
    output = programdata / "logs" / "hub-manager-app" / "delete-hub-data.json"
    output.unlink(missing_ok=True)

    app_env = {
        "IMMOAPP_TEST_PROGRAMDATA_ROOT": str(programdata),
        "IMMOAPP_APPDATA_ROOT": str(programdata),
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT": "1",
        "IMMOAPP_TEST_ASSUME_WINDOWS_ADMIN": "1",
        "IMMOAPP_HUB_FRONT_DOOR_URL": e2e_front_door_url,
    }
    with HubManagerAppDriver.launch(
        repo_root,
        e2e_client_python,
        env_overrides=app_env,
    ) as hub_manager:
        window = hub_manager.wait_for_main_window(timeout=60.0)
        hub_manager.wait_for_text(window, "Refresh status: GO", timeout=220.0)
        hub_manager.click_button(
            window,
            "Danger Zone: delete Hub data",
            automation_id="hubManagerAction_delete-hub-data",
        )
        typed_confirmation = hub_manager.wait_for_window(
            title="Confirm permanent deletion",
            timeout=30.0,
        )
        hub_manager.set_first_edit_text(typed_confirmation, "DELETE HUB DATA")
        hub_manager.click_button(typed_confirmation, "OK")

        final_confirmation = hub_manager.wait_for_window(
            title="Danger Zone: delete Hub data",
            timeout=20.0,
        )
        hub_manager.click_button(final_confirmation, "Yes")
        login = hub_manager.wait_for_login(timeout=30.0)
        hub_manager.sign_in_owner(login)
        payload = _wait_for_delete_evidence(output)

        assert payload["proof_result"] == "GO"
        assert payload["reason_code"] == "hub_data_deleted"
        assert [Path(str(path)) for path in payload["target_roots"]] == [
            programdata / "config",
            programdata / "data",
            programdata / "runtime",
        ]
        assert not (programdata / "config" / "delete-target.txt").exists()
        assert not (programdata / "data" / "delete-target.txt").exists()
        assert not (programdata / "runtime" / "delete-target.txt").exists()
        owner_authorization = (
            programdata / "logs" / "hub-manager-app" / "hub_owner_authorization.json"
        )
        deadline = time.monotonic() + 10.0
        while owner_authorization.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not owner_authorization.exists()

    health = requests.get(f"{e2e_front_door_url}/api/v1/health/", timeout=10.0)
    assert health.status_code == 200


def test_delete_hub_data_succeeds_with_db_backed_owner_evidence_on_disposable_root(
    repo_root: Path,
    e2e_front_door_url: str,
    tmp_path: Path,
) -> None:
    assert e2e_front_door_url
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    env = _disposable_hub_env(programdata)
    _setup_disposable_hub(repo_root, programdata, env)

    evidence_path, evidence_payload, evidence_result = _create_owner_delete_evidence(
        repo_root,
        programdata,
        base_url=e2e_front_door_url,
        password="admin",
        env=env,
    )
    assert evidence_result.returncode == 0, evidence_result.stderr + evidence_result.stdout
    assert evidence_payload["proof_result"] == "GO"
    assert evidence_payload["source"] == "hub_db"
    assert evidence_payload["action"] == "delete_hub_data"
    assert "password" not in f"{evidence_result.stdout}\n{evidence_result.stderr}".lower()
    assert "token" not in f"{evidence_result.stdout}\n{evidence_result.stderr}".lower()

    result = _run_delete_hub_data(
        repo_root,
        programdata,
        evidence_path,
        base_url=e2e_front_door_url,
        env=env,
    )

    output = programdata / "logs" / "delete_hub_data.json"
    assert result.returncode == 0, result.stderr + result.stdout
    payload = _read_json(output)
    assert payload["proof_result"] == "GO"
    assert payload["reason_code"] == "hub_data_deleted"
    target_roots = [Path(str(item)) for item in payload["target_roots"]]
    assert target_roots == [
        programdata / "config",
        programdata / "data",
        programdata / "runtime",
    ]
    assert not (programdata / "config").exists()
    assert not (programdata / "data").exists()
    assert not (programdata / "runtime").exists()
    assert (programdata / "logs").exists()
    assert Path(r"C:\ProgramData\ImmoApp") not in target_roots
    assert "password" not in f"{result.stdout}\n{result.stderr}".lower()
    assert "token" not in f"{result.stdout}\n{result.stderr}".lower()


def test_delete_hub_data_preserves_disposable_root_when_owner_evidence_is_no_go(
    repo_root: Path,
    e2e_front_door_url: str,
    tmp_path: Path,
) -> None:
    assert e2e_front_door_url
    programdata = tmp_path / "ProgramData" / "ImmoApp"
    env = _disposable_hub_env(programdata)
    _setup_disposable_hub(repo_root, programdata, env)

    evidence_path, evidence_payload, evidence_result = _create_owner_delete_evidence(
        repo_root,
        programdata,
        base_url=e2e_front_door_url,
        password="wrong-password",
        env=env,
    )
    assert evidence_result.returncode != 0
    assert evidence_payload["proof_result"] == "NO-GO"
    assert evidence_payload["reason_code"] == "hub_owner_authorization_password_invalid"

    result = _run_delete_hub_data(
        repo_root,
        programdata,
        evidence_path,
        base_url=e2e_front_door_url,
        env=env,
    )

    output = programdata / "logs" / "delete_hub_data.json"
    assert result.returncode != 0
    payload = _read_json(output)
    assert payload["proof_result"] == "NO-GO"
    assert payload["reason_code"] == "hub_delete_owner_authorization_not_go"
    assert (programdata / "config" / "delete-target.txt").is_file()
    assert (programdata / "data" / "delete-target.txt").is_file()
    assert (programdata / "runtime" / "delete-target.txt").is_file()
    combined_output = f"{result.stdout}\n{result.stderr}"
    assert "password" not in combined_output.lower()
    assert "token" not in combined_output.lower()
