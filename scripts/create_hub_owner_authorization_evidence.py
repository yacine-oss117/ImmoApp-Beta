from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.hub_manager_access_client import (  # noqa: E402
    HubManagerAccessClientError,
    request_owner_authorization,
)
from core.contracts.hub_manager_authorization import (  # noqa: E402
    DELETE_HUB_DATA_ACTION,
    PROTECTED_ACTIONS,
    authorization_scope,
)


def _programdata_root() -> Path:
    test_root = os.environ.get("IMMOAPP_TEST_PROGRAMDATA_ROOT")
    if test_root and os.environ.get("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return Path(test_root)
    return Path(os.environ.get("IMMOAPP_APPDATA_ROOT", r"C:\ProgramData\ImmoApp"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _password_from_input(args: argparse.Namespace) -> str:
    password_value = getattr(args, "password_value", "")
    if password_value:
        return str(password_value)
    if args.password_env:
        return os.environ.get(args.password_env, "")
    if args.password_stdin:
        return sys.stdin.read().rstrip("\r\n")
    raise ValueError("Use --password-stdin or --password-env; plaintext CLI passwords are refused.")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(tmp, path)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _approved_output_path(path: Path, root: Path) -> Path:
    approved_roots = (root / "config", root / "logs", root / "tmp")
    if not any(_is_under(path, approved_root) for approved_root in approved_roots):
        raise ValueError("hub_owner_authorization_output_path_unapproved")
    return path


def _base_payload(reason_code: str, *, action: str) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        scope = authorization_scope(action)
    except ValueError:
        scope = "hub_manager_protected_action"
    return {
        "kind": "immoapp_hub_owner_authorization_evidence",
        "schema_version": 3,
        "created_at_utc": now.isoformat(),
        "expires_at_utc": now.isoformat(),
        "proof_result": "NO-GO",
        "owner_authorization_status": "NO-GO",
        "reason_code": reason_code,
        "action": action,
        "authorization_scope": scope,
        "source": "hub_db",
        "plaintext_password_written": False,
        "session_token_written": False,
        "agency_install_status": "NO_GO",
        "public_beta_status": "NO_GO",
    }


def create_evidence(args: argparse.Namespace) -> dict[str, Any]:
    action = str(args.action or DELETE_HUB_DATA_ACTION)
    if action not in PROTECTED_ACTIONS:
        return _base_payload("hub_owner_authorization_wrong_action", action=action)
    root = _programdata_root()
    identity_path = Path(args.hub_identity_json or root / "config" / "hub_identity.json")
    state_path = Path(args.hub_state_manifest_json or root / "config" / "hub_state_manifest.json")
    try:
        identity = _read_json(identity_path)
        state = _read_json(state_path)
    except Exception:
        return _base_payload("hub_owner_authorization_hub_state_unreadable", action=action)
    hub_id = str(identity.get("hub_id") or "")
    if not hub_id or hub_id != str(state.get("hub_id") or ""):
        return _base_payload("hub_owner_authorization_hub_state_mismatch", action=action)

    identifier = str(args.username or "").strip()
    if not identifier:
        return _base_payload("hub_owner_authorization_username_required", action=action)
    base_url = str(getattr(args, "base_url", "") or "").strip()
    if not base_url:
        return _base_payload("hub_owner_authorization_hub_connection_missing", action=action)
    try:
        password = _password_from_input(args)
        return request_owner_authorization(
            base_url=base_url,
            username=identifier,
            password=password,
            action=action,
            hub_binding={
                "hub_id": hub_id,
                "hub_display_name": str(identity.get("hub_display_name") or ""),
                "hub_identity_sha256": _sha256(identity_path),
                "hub_state_manifest_sha256": _sha256(state_path),
                "hub_state_install_lineage": str(state.get("install_lineage") or ""),
            },
        )
    except HubManagerAccessClientError as exc:
        return _base_payload(exc.reason_code, action=action)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Hub owner/admin authorization evidence.")
    parser.add_argument("--username", required=True, help="Owner/admin username or email.")
    parser.add_argument("--password-stdin", action="store_true", help="Read password from stdin.")
    parser.add_argument("--password-env", default="", help="Read password from named env var.")
    parser.add_argument("--action", default=DELETE_HUB_DATA_ACTION)
    parser.add_argument("--base-url", default=os.environ.get("IMMOAPP_HUB_FRONT_DOOR_URL", ""))
    parser.add_argument("--hub-identity-json", default="")
    parser.add_argument("--hub-state-manifest-json", default="")
    parser.add_argument("--output-json", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = _programdata_root()
    output = Path(args.output_json or root / "logs" / "hub_owner_authorization.json")
    try:
        output = _approved_output_path(output, root)
    except ValueError as exc:
        output = root / "logs" / "hub_owner_authorization.json"
        payload = _base_payload(str(exc), action=str(args.action or ""))
        _write_json(output, payload)
        print(output)
        return 1
    try:
        payload = create_evidence(args)
    except Exception as exc:
        payload = _base_payload(exc.__class__.__name__, action=str(args.action or ""))
    _write_json(output, payload)
    print(output)
    return 0 if payload.get("proof_result") == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
