"""
Guardrail tests: write endpoints must include idempotency handling.

This prevents regressions where network retries create duplicate writes.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]

_TARGETS: dict[Path, list[str]] = {
    _REPO_ROOT
    / "server"
    / "api"
    / "views_templates.py": [
        "templates_list",
        "template_detail",
        "templates_reset",
    ],
    _REPO_ROOT
    / "server"
    / "api"
    / "views_locations.py": [
        "locations_endpoint",
    ],
    _REPO_ROOT
    / "server"
    / "api"
    / "views_users.py": [
        "users_list",
        "user_detail",
    ],
    _REPO_ROOT
    / "server"
    / "api"
    / "views_agency.py": [
        "agency_settings_set",
        "agency_settings_serial",
        "agency_media_presign",
        "agency_media_complete",
    ],
    _REPO_ROOT
    / "server"
    / "api"
    / "views_storage.py": [
        "storage_presign_upload",
        "storage_complete_upload",
        "storage_delete",
    ],
}


def _load_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name} not found in AST")


def _has_call(func: ast.FunctionDef, target_name: str) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == target_name:
            return True
    return False


def test_write_endpoints_have_idempotency_guard() -> None:
    for path, funcs in _TARGETS.items():
        tree = _load_tree(path)
        for func_name in funcs:
            fn = _find_function(tree, func_name)
            assert _has_call(
                fn, "check_idempotency"
            ), f"{path.name}:{func_name} must call check_idempotency(...)"
            assert _has_call(
                fn, "store_idempotency"
            ), f"{path.name}:{func_name} must call store_idempotency(...)"
