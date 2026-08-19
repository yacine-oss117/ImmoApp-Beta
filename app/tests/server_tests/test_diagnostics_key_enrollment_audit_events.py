from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_SERVICE_PATH = _REPO_ROOT / "server" / "services" / "diagnostics_keys.py"

_REQUIRED_EVENTS = {
    "diagnostics_key_enroll_requested",
    "diagnostics_key_enroll_approved",
    "diagnostics_key_enroll_denied",
    "diagnostics_key_registered",
    "diagnostics_key_rotated",
    "diagnostics_key_revoked",
    "diagnostics_enrollment_token_issued",
    "diagnostics_enrollment_token_consumed",
}


def _extract_logged_event_types(tree: ast.Module) -> set[str]:
    event_types: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_log_event":
            continue
        for kw in node.keywords:
            if kw.arg != "event_type":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                event_types.add(kw.value.value)
    return event_types


def _function_has_log_call(tree: ast.Module, function_name: str, event_type: str) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if not isinstance(call.func, ast.Name) or call.func.id != "_log_event":
                continue
            for kw in call.keywords:
                if kw.arg == "event_type" and isinstance(kw.value, ast.Constant):
                    if kw.value.value == event_type:
                        return True
    return False


def test_diagnostics_key_service_logs_required_audit_event_types() -> None:
    tree = ast.parse(_SERVICE_PATH.read_text(encoding="utf-8"))
    logged = _extract_logged_event_types(tree)
    missing = sorted(_REQUIRED_EVENTS - logged)
    assert not missing, f"Missing diagnostics audit events: {missing}"


def test_diagnostics_key_rotation_and_revoke_log_lifecycle_events() -> None:
    tree = ast.parse(_SERVICE_PATH.read_text(encoding="utf-8"))
    assert _function_has_log_call(tree, "rotate_signing_key", "diagnostics_key_rotated")
    assert _function_has_log_call(tree, "revoke_signing_key", "diagnostics_key_revoked")
