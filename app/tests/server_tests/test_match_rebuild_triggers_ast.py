"""
Match rebuild trigger guardrails.

These AST checks prevent accidental regressions where status changes on
clients/listings stop enqueueing match pair rebuild tasks.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_LISTINGS_FILE = _REPO_ROOT / "server" / "services" / "listings.py"
_CLIENTS_FILE = _REPO_ROOT / "server" / "services" / "clients.py"


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


def _has_status_compare(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Compare):
            continue
        if len(node.ops) != 1 or not isinstance(node.ops[0], ast.NotEq):
            continue
        left = node.left
        right = node.comparators[0]
        if (
            isinstance(left, ast.Name)
            and isinstance(right, ast.Name)
            and left.id == "previous_status"
            and right.id == "next_status"
        ):
            return True
    return False


def test_listing_upsert_rebuilds_offer_pairs_on_status_change() -> None:
    func = _load_func(_LISTINGS_FILE, "upsert_listing")
    calls = _collect_calls(func)
    assert _has_status_compare(func), "upsert_listing must compare previous_status != next_status"
    assert (
        "_enqueue_offer_rebuilds_with_hints" in calls
        or "_run_listing_upsert_post_commit" in calls
        or "_listing_upsert_post_commit_callback" in calls
    ), "upsert_listing must schedule hint-aware offer rebuilds"
    assert (
        "enqueue_rebuild_offer_pairs" in calls
        or "_run_listing_upsert_post_commit" in calls
        or "_listing_upsert_post_commit_callback" in calls
    ), "upsert_listing must schedule fallback offer rebuilds for offers without hints"


def test_client_upsert_rebuilds_pairs_on_status_change() -> None:
    func = _load_func(_CLIENTS_FILE, "upsert_client")
    calls = _collect_calls(func)
    assert _has_status_compare(func), "upsert_client must compare previous_status != next_status"
    assert (
        "enqueue_rebuild_client_pairs" in calls or "_enqueue_client_pairs_callback" in calls
    ), "upsert_client must enqueue pair rebuilds when client status changes"
