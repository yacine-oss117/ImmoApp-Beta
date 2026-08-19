"""
RBAC guardrails for high-risk endpoints.

These tests enforce that sensitive API endpoints call the RBAC helpers
(`require_manager`, `require_hard_delete`, `require_superuser`) to prevent
accidental permission regressions.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]

REQUIRES_MANAGER = {
    "agency_settings_set",
    "agency_media_presign",
    "agency_media_complete",
    "templates_list",
    "template_detail",
    "templates_reset",
    "audit_logs",
    "audit_count",
    "record_visibility",
    "users_list",
    "user_detail",
}

REQUIRES_HARD_DELETE = {
    "client_purge",
    "listing_purge",
    "offer_purge",
    "demande_purge",
    "crm_contract_purge",
    "crm_visit_purge",
}

REQUIRES_SUPERUSER = {
    "audit_purge",
    "notifications_purge",
    "simulation_start",
    "simulation_delete",
    "simulation_save",
    "simulation_status",
}

REQUIRES_OWNER = {
    "user_detail",
}


def _extract_function_calls(tree: ast.AST) -> dict[str, set[str]]:
    calls_by_func: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        call_names: set[str] = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if isinstance(func, ast.Name):
                call_names.add(func.id)
            elif isinstance(func, ast.Attribute):
                call_names.add(func.attr)
        calls_by_func[node.name] = call_names
    return calls_by_func


def _load_calls() -> dict[str, set[str]]:
    calls: dict[str, set[str]] = {}
    for py_file in (_REPO_ROOT / "server" / "api").glob("views_*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        calls.update(_extract_function_calls(tree))
    return calls


def _assert_guard(calls: dict[str, set[str]], func_name: str, guard_name: str) -> None:
    assert func_name in calls, f"RBAC guard test missing function: {func_name}"
    assert (
        guard_name in calls[func_name]
    ), f"RBAC guard missing: {func_name} must call {guard_name}()"


def test_manager_guards_present() -> None:
    calls = _load_calls()
    for func_name in sorted(REQUIRES_MANAGER):
        _assert_guard(calls, func_name, "require_manager")


def test_hard_delete_guards_present() -> None:
    calls = _load_calls()
    for func_name in sorted(REQUIRES_HARD_DELETE):
        _assert_guard(calls, func_name, "require_hard_delete")


def test_superuser_guards_present() -> None:
    calls = _load_calls()
    for func_name in sorted(REQUIRES_SUPERUSER):
        _assert_guard(calls, func_name, "require_superuser")


def test_owner_guards_present() -> None:
    calls = _load_calls()
    for func_name in sorted(REQUIRES_OWNER):
        _assert_guard(calls, func_name, "require_owner")
