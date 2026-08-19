"""
Guardrails for upsert transactional locking.

These checks ensure update paths keep read+write in one transaction and use
row-level locks to avoid TOCTOU races.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_CLIENTS_SERVICE_FILE = _REPO_ROOT / "server" / "services" / "clients.py"
_LISTINGS_SERVICE_FILE = _REPO_ROOT / "server" / "services" / "listings.py"
_CLIENTS_READ_FILE = _REPO_ROOT / "core" / "data" / "client_repo_read.py"
_LISTINGS_READ_FILE = _REPO_ROOT / "core" / "data" / "listing_repo_read.py"


def _load_func(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name} not found in {path}")


def _collect_calls(func: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Name):
            names.add(callee.id)
        elif isinstance(callee, ast.Attribute):
            names.add(callee.attr)
    return names


def _function_source(path: Path, func: ast.FunctionDef) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[func.lineno - 1 : func.end_lineno])


def test_client_upsert_uses_locked_read_inside_transaction() -> None:
    func = _load_func(_CLIENTS_SERVICE_FILE, "upsert_client")
    calls = _collect_calls(func)
    assert "get_client_by_id_for_update" in calls, "upsert_client must use FOR UPDATE read helper"
    assert (
        "session" not in calls
    ), "upsert_client must not do pre-transaction get_uow().session() reads"


def test_listing_upsert_uses_locked_read_inside_transaction() -> None:
    func = _load_func(_LISTINGS_SERVICE_FILE, "upsert_listing")
    calls = _collect_calls(func)
    assert "get_listing_by_id_for_update" in calls, "upsert_listing must use FOR UPDATE read helper"
    assert (
        "session" not in calls
    ), "upsert_listing must not do pre-transaction get_uow().session() reads"


def test_client_read_lock_helper_uses_for_update_sql() -> None:
    func = _load_func(_CLIENTS_READ_FILE, "get_client_by_id_for_update")
    source = _function_source(_CLIENTS_READ_FILE, func)
    assert "FOR UPDATE" in source, "client lock helper must issue SELECT ... FOR UPDATE"


def test_listing_read_lock_helper_uses_for_update_sql() -> None:
    func = _load_func(_LISTINGS_READ_FILE, "get_listing_by_id_for_update")
    source = _function_source(_LISTINGS_READ_FILE, func)
    assert "FOR UPDATE" in source, "listing lock helper must issue SELECT ... FOR UPDATE"
