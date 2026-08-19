from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from app.hub_manager_actions import ACTION_BY_KEY

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_smoke,
    pytest.mark.hub_manager_powershell_guard,
]

_OUTPUT_DIR = Path(r"C:\ProgramData\ImmoApp\logs\hub-manager-app")
_GENERIC_PROTECTED_ACTIONS = [
    "finish-hub-setup",
    "rename-hub",
    "install-runtime-candidate",
    "install-runtime-artifact",
    "remove-runtime-candidate",
    "cleanup-runtime-logs",
    "backup-now",
    "logs",
]


def _run_hub_manager_action(
    repo_root: Path,
    action: str,
    *,
    output_json: Path,
    owner_evidence_json: Path | None = None,
    hub_base_url: str = "",
) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo_root / "scripts" / "hub_manager.ps1"),
        "-Action",
        action,
        "-OutputJson",
        str(output_json),
    ]
    if owner_evidence_json is not None:
        command.extend(["-OwnerAuthorizationEvidenceJson", str(owner_evidence_json)])
    if hub_base_url:
        command.extend(["-HubBaseUrl", hub_base_url])
    return subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _assert_blocked_before_action(
    *,
    result: subprocess.CompletedProcess[str],
    output_json: Path,
    action: str,
    reason_code: str,
) -> None:
    assert result.returncode != 0
    assert output_json.is_file()
    payload = _read_json(output_json)
    assert payload["kind"] == "immoapp_hub_manager_owner_authorization"
    assert payload["action"] == action
    assert payload["proof_result"] == "NO-GO"
    assert payload["protected_action_blocked"] is True
    assert payload["reason_code"] == reason_code
    combined_output = f"{result.stdout}\n{result.stderr}"
    normalized_output = " ".join(combined_output.split())
    assert (
        "Protected Hub Manager action requires active Hub owner/admin authorization"
        in normalized_output
    )
    assert "password" not in combined_output.lower()
    assert "token" not in combined_output.lower()


@pytest.mark.parametrize("action", _GENERIC_PROTECTED_ACTIONS)
def test_direct_protected_hub_manager_powershell_action_requires_owner_evidence(
    repo_root: Path,
    action: str,
) -> None:
    output_json = _OUTPUT_DIR / f"direct_guard_{action}_{uuid.uuid4().hex}.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    try:
        if action in ACTION_BY_KEY:
            assert ACTION_BY_KEY[action].requires_owner_authorization
        else:
            assert action in {"install-runtime-candidate", "remove-runtime-candidate"}
        result = _run_hub_manager_action(repo_root, action, output_json=output_json)

        _assert_blocked_before_action(
            result=result,
            output_json=output_json,
            action=action,
            reason_code="hub_delete_owner_authorization_required",
        )
    finally:
        output_json.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("evidence_payload", "reason_code"),
    [
        pytest.param(
            {"kind": "not_owner_authorization", "schema_version": 3},
            "hub_delete_owner_authorization_invalid_kind",
            id="wrong-kind",
        ),
        pytest.param(
            {
                "kind": "immoapp_hub_owner_authorization_evidence",
                "schema_version": 3,
                "source": "local_json",
            },
            "hub_delete_owner_authorization_source_invalid",
            id="wrong-source",
        ),
        pytest.param(
            {
                "kind": "immoapp_hub_owner_authorization_evidence",
                "schema_version": 3,
                "source": "hub_db",
                "action": "cleanup-runtime-logs",
            },
            "hub_delete_owner_authorization_action_invalid",
            id="wrong-action",
        ),
    ],
)
def test_direct_protected_hub_manager_powershell_action_rejects_forged_evidence(
    repo_root: Path,
    evidence_payload: dict[str, Any],
    reason_code: str,
) -> None:
    action = "backup-now"
    output_json = _OUTPUT_DIR / f"direct_guard_forged_{uuid.uuid4().hex}.json"
    evidence_json = _OUTPUT_DIR / f"forged_owner_evidence_{uuid.uuid4().hex}.json"
    try:
        _write_json(evidence_json, evidence_payload)
        result = _run_hub_manager_action(
            repo_root,
            action,
            output_json=output_json,
            owner_evidence_json=evidence_json,
        )

        _assert_blocked_before_action(
            result=result,
            output_json=output_json,
            action=action,
            reason_code=reason_code,
        )
    finally:
        output_json.unlink(missing_ok=True)
        evidence_json.unlink(missing_ok=True)


def test_direct_protected_hub_manager_powershell_action_rejects_malformed_evidence(
    repo_root: Path,
) -> None:
    action = "backup-now"
    output_json = _OUTPUT_DIR / f"direct_guard_malformed_{uuid.uuid4().hex}.json"
    evidence_json = _OUTPUT_DIR / f"malformed_owner_evidence_{uuid.uuid4().hex}.json"
    try:
        evidence_json.parent.mkdir(parents=True, exist_ok=True)
        evidence_json.write_text("{not json", encoding="utf-8")
        result = _run_hub_manager_action(
            repo_root,
            action,
            output_json=output_json,
            owner_evidence_json=evidence_json,
        )

        _assert_blocked_before_action(
            result=result,
            output_json=output_json,
            action=action,
            reason_code="hub_delete_owner_authorization_malformed_json",
        )
    finally:
        output_json.unlink(missing_ok=True)
        evidence_json.unlink(missing_ok=True)


def test_running_hub_rejects_complete_locally_forged_owner_evidence_before_backup(
    repo_root: Path,
    e2e_front_door_url: str,
) -> None:
    action = "backup-now"
    identity_path = Path(r"C:\ProgramData\ImmoApp\config\hub_identity.json")
    state_path = Path(r"C:\ProgramData\ImmoApp\config\hub_state_manifest.json")
    identity = _read_json(identity_path)
    state = _read_json(state_path)
    now = datetime.now(UTC).replace(microsecond=0)
    evidence_payload = {
        "kind": "immoapp_hub_owner_authorization_evidence",
        "schema_version": 3,
        "created_at_utc": now.isoformat(),
        "expires_at_utc": (now + timedelta(minutes=5)).isoformat(),
        "proof_result": "GO",
        "owner_authorization_status": "GO",
        "reason_code": "hub_owner_authorization_verified",
        "action": action,
        "authorization_scope": "hub_manager_protected_action",
        "source": "hub_db",
        "evidence_nonce": uuid.uuid4().hex,
        "actor_user_id": 1,
        "actor_role": "manager",
        "actor_is_owner": True,
        "actor_can_hard_delete": False,
        "actor_is_superuser": False,
        "authorized_role": "agency_owner",
        "agency_id": 1,
        "hub_id": state["hub_id"],
        "hub_display_name": identity.get("hub_display_name", ""),
        "hub_identity_sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest(),
        "hub_state_manifest_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "hub_state_install_lineage": state["install_lineage"],
        "plaintext_password_written": False,
        "session_token_written": False,
    }
    output_json = _OUTPUT_DIR / f"direct_guard_complete_forgery_{uuid.uuid4().hex}.json"
    evidence_json = _OUTPUT_DIR / f"complete_forged_owner_evidence_{uuid.uuid4().hex}.json"
    backup_evidence = Path(r"C:\ProgramData\ImmoApp\logs\managed_wsl2_runtime_backup_evidence.json")
    backup_mtime = backup_evidence.stat().st_mtime_ns if backup_evidence.exists() else None
    try:
        _write_json(evidence_json, evidence_payload)
        result = _run_hub_manager_action(
            repo_root,
            action,
            output_json=output_json,
            owner_evidence_json=evidence_json,
            hub_base_url=e2e_front_door_url,
        )

        _assert_blocked_before_action(
            result=result,
            output_json=output_json,
            action=action,
            reason_code="hub_owner_authorization_not_confirmed",
        )
        if backup_mtime is None:
            assert not backup_evidence.exists()
        else:
            assert backup_evidence.stat().st_mtime_ns == backup_mtime
    finally:
        output_json.unlink(missing_ok=True)
        evidence_json.unlink(missing_ok=True)
