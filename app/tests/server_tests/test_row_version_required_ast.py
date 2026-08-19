"""
Guardrail tests: updates must require row_version.

These AST checks prevent accidental removal of row_version enforcement from
update endpoints that rely on optimistic concurrency control.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]

_TARGETS: dict[Path, list[str]] = {
    _REPO_ROOT / "server" / "api" / "views_clients_detail.py": ["client_detail"],
    _REPO_ROOT / "server" / "api" / "views_listings_detail.py": ["listing_detail"],
    _REPO_ROOT / "server" / "api" / "views_demandes.py": ["demande_detail"],
    _REPO_ROOT / "server" / "api" / "views_offers.py": ["offer_detail"],
    _REPO_ROOT / "server" / "api" / "views_crm_contracts.py": ["crm_contract_detail"],
    _REPO_ROOT / "server" / "api" / "views_crm_visits.py": ["crm_visit_detail"],
    _REPO_ROOT / "server" / "api" / "views_crm_articles.py": ["crm_article_detail"],
    _REPO_ROOT / "server" / "api" / "views_visibility.py": ["record_visibility"],
}


def _load_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name} not found in {tree}")


def _has_require_row_version(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not isinstance(callee, ast.Name) or callee.id != "validate_payload":
            continue
        for kw in node.keywords:
            if (
                kw.arg == "require_row_version"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                return True
    return False


def test_update_endpoints_require_row_version() -> None:
    for path, funcs in _TARGETS.items():
        tree = _load_tree(path)
        for name in funcs:
            func = _find_function(tree, name)
            assert _has_require_row_version(
                func
            ), f"{name} must call validate_payload(..., require_row_version=True)"
