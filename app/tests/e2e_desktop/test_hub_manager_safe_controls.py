from __future__ import annotations

import json
import subprocess
import time
import zipfile
from json import JSONDecodeError
from pathlib import Path
from urllib.parse import unquote

import pytest

from app.tests.e2e_desktop.hub_manager_driver import (
    SUPPORT_OUTPUT_DIR,
    HubManagerAppDriver,
    load_json,
    newest_support_bundle,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.hub_manager_safe_controls,
]


def _run_powershell(
    script: str,
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _clipboard_text() -> str:
    result = _run_powershell(
        "$value = Get-Clipboard -Raw -ErrorAction SilentlyContinue; "
        "if ($null -ne $value) { [Console]::Out.Write([string]$value) }"
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _set_clipboard_text(value: str) -> None:
    result = _run_powershell(
        "[Console]::InputEncoding = [Text.Encoding]::UTF8; "
        "$value = [Console]::In.ReadToEnd(); Set-Clipboard -Value $value",
        input_text=value,
    )
    assert result.returncode == 0, result.stderr


def _explorer_locations() -> set[str]:
    result = _run_powershell(
        "$shell = New-Object -ComObject Shell.Application; "
        "@($shell.Windows()) | ForEach-Object { [Console]::Out.WriteLine($_.LocationURL) }"
    )
    assert result.returncode == 0, result.stderr
    return {
        unquote(line.strip()).rstrip("/").lower()
        for line in result.stdout.splitlines()
        if line.strip()
    }


def _close_explorer_location(location: str) -> None:
    escaped = location.replace("'", "''")
    _run_powershell(
        "$target = '" + escaped + "'; $shell = New-Object -ComObject Shell.Application; "
        "@($shell.Windows()) | Where-Object { "
        "([string]$_.LocationURL).TrimEnd('/').ToLowerInvariant() -eq $target "
        "} | ForEach-Object { $_.Quit() }"
    )


def _wait_for_explorer_location(expected: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_locations: set[str] = set()
    while time.monotonic() < deadline:
        last_locations = _explorer_locations()
        if expected in last_locations:
            return
        time.sleep(0.25)
    raise AssertionError(
        f"Explorer did not open the Hub Manager evidence folder. Seen: {last_locations}"
    )


def _mtime_ns(path: Path) -> int:
    return path.stat().st_mtime_ns if path.exists() else 0


def _wait_for_json_update(
    path: Path,
    *,
    after_mtime_ns: int,
    timeout: float = 220.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            if path.is_file() and path.stat().st_mtime_ns > after_mtime_ns:
                return load_json(path)
        except (JSONDecodeError, OSError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise AssertionError(
        f"Hub Manager evidence was not freshly written: {path}. Last error: {last_error}"
    )


def _assert_support_bundle_excludes_runtime_secret_material(support_bundle: Path) -> None:
    forbidden_snippets = (
        "change-before-start",
        "token_file=/",
        "/run/immoapp-secrets/openbao.token",
        "WITH PASSWORD 'change-before-start'",
        "dev-root-token-id",
        "hub-manager-e2e-owner-name",
        "hub-manager-e2e-owner@example.test",
        "hub-manager-e2e-evidence-nonce",
        "hub-manager-e2e-owner-password",
        "hub-manager-e2e-session-token",
    )
    with zipfile.ZipFile(support_bundle) as bundle:
        names = set(bundle.namelist())
        assert "manifest.json" in names
        assert "README.txt" in names
        for info in bundle.infolist():
            if info.file_size > 500_000:
                continue
            try:
                text = bundle.read(info.filename).decode("utf-8")
            except UnicodeDecodeError:
                continue
            for snippet in forbidden_snippets:
                assert snippet not in text, f"{snippet!r} leaked in {info.filename}"


def test_safe_controls_execute_real_effects(
    repo_root: Path,
    e2e_front_door_url: str,
    e2e_client_python: Path,
    artifact_dir: Path,
) -> None:
    expected_folder = SUPPORT_OUTPUT_DIR.resolve().as_uri().rstrip("/").lower()
    previous_clipboard = _clipboard_text()
    owner_evidence_path = SUPPORT_OUTPUT_DIR / "hub_owner_authorization.json"
    previous_owner_evidence = (
        owner_evidence_path.read_bytes() if owner_evidence_path.is_file() else None
    )
    _close_explorer_location(expected_folder)
    try:
        with HubManagerAppDriver.launch(repo_root, e2e_client_python) as hub_manager:
            window = hub_manager.wait_for_main_window()
            hub_manager.wait_for_text(window, "Refresh status: GO", timeout=220.0)

            actions = (
                ("Refresh status", "status", "immoapp_managed_wsl2_runtime_start_evidence"),
                (
                    "Connection details",
                    "connection-details",
                    "immoapp_hub_manager_connection_details",
                ),
                ("Check Hub engine", "runtime-status", "immoapp_hub_runtime_detection"),
                (
                    "Check network access",
                    "firewall-status",
                    "immoapp_hub_manager_firewall_status",
                ),
            )
            for label, action, expected_kind in actions:
                output = SUPPORT_OUTPUT_DIR / f"{action}.json"
                output_mtime_ns = _mtime_ns(output)
                hub_manager.click_button(
                    window,
                    label,
                    automation_id=f"hubManagerAction_{action}",
                )
                payload = _wait_for_json_update(
                    output,
                    after_mtime_ns=output_mtime_ns,
                )
                hub_manager.wait_for_action_text(window, f"{label}: GO", timeout=220.0)
                assert payload["kind"] == expected_kind

            runtime_status_output = SUPPORT_OUTPUT_DIR / "runtime-status.json"
            runtime_status_mtime_ns = _mtime_ns(runtime_status_output)
            hub_manager.click_button(
                window,
                automation_id="hub-secondary-action",
            )
            _wait_for_json_update(
                runtime_status_output,
                after_mtime_ns=runtime_status_mtime_ns,
            )
            hub_manager.wait_for_action_text(window, "Check Hub engine: GO", timeout=220.0)

            _set_clipboard_text("hub-manager-e2e-before-copy")
            hub_manager.click_button(
                window,
                "Copy connection URL",
                automation_id="hubManagerAction_copy-url",
            )
            hub_manager.wait_for_action_text(window, "Copy connection URL: GO", timeout=45.0)
            assert _clipboard_text().strip().rstrip("/") == e2e_front_door_url.rstrip("/")

            owner_evidence_path.write_text(
                json.dumps(
                    {
                        "kind": "immoapp_hub_owner_authorization_evidence",
                        "schema_version": 3,
                        "proof_result": "GO",
                        "owner_authorization_status": "GO",
                        "action": "backup-now",
                        "authorization_scope": "hub_manager_protected_action",
                        "source": "hub_db",
                        "actor_username": "hub-manager-e2e-owner-name",
                        "actor_email": "hub-manager-e2e-owner@example.test",
                        "evidence_nonce": "hub-manager-e2e-evidence-nonce",
                        "password": "hub-manager-e2e-owner-password",
                        "session_token": "hub-manager-e2e-session-token",
                    }
                ),
                encoding="utf-8",
            )
            support_started_at = time.time()
            hub_manager.click_button(
                window,
                "Collect support file",
                automation_id="hubManagerAction_support",
            )
            hub_manager.wait_for_action_text(window, "Collect support file: GO", timeout=180.0)
            support_bundle = newest_support_bundle(after_timestamp=support_started_at)
            _assert_support_bundle_excludes_runtime_secret_material(support_bundle)

            hub_manager.click_button(window, "Show technical details")
            hub_manager.wait_for_text(window, "Hide technical details", timeout=10.0)
            hub_manager.click_button(window, "Open evidence folder")
            _wait_for_explorer_location(expected_folder)

            screenshot = artifact_dir / "hub_manager_safe_controls.png"
            window.capture_as_image().save(screenshot)
            assert screenshot.is_file()
    finally:
        _set_clipboard_text(previous_clipboard)
        _close_explorer_location(expected_folder)
        if previous_owner_evidence is None:
            owner_evidence_path.unlink(missing_ok=True)
        else:
            owner_evidence_path.parent.mkdir(parents=True, exist_ok=True)
            owner_evidence_path.write_bytes(previous_owner_evidence)


@pytest.mark.e2e_smoke
@pytest.mark.hub_manager_conflict
def test_start_is_blocked_before_touching_managed_runtime_when_docker_owns_ports(
    repo_root: Path,
    e2e_client_python: Path,
) -> None:
    output = SUPPORT_OUTPUT_DIR / "start.json"
    output_mtime_ns = _mtime_ns(output)
    with HubManagerAppDriver.launch(repo_root, e2e_client_python) as hub_manager:
        window = hub_manager.wait_for_main_window()
        hub_manager.wait_for_text(window, "Refresh status: GO", timeout=220.0)
        hub_manager.click_button(window, "Start Hub", automation_id="hubManagerAction_start")
        evidence = _wait_for_json_update(
            output,
            after_mtime_ns=output_mtime_ns,
            timeout=120.0,
        )
        hub_manager.wait_for_action_text(window, "Start Hub: NO-GO", timeout=120.0)

        assert evidence["reason_code"] == "managed_wsl2_pre_start_port_contamination"
        assert evidence["pre_start_backend_direct_reachable"] is True
