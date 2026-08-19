"""
Static contract checks for match count endpoints.

These checks keep UI/server contracts aligned without requiring Django runtime.
"""

from __future__ import annotations

import ast
from pathlib import Path

_FILE = Path(__file__).parents[3] / "server" / "api" / "views_matches.py"
_TARGETS = {
    "matches_count_clients",
    "matches_count_demandes",
    "matches_count_listings",
    "matches_count_offers",
}


def _load_tree() -> ast.Module:
    return ast.parse(_FILE.read_text(encoding="utf-8"))


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name} not found in {_FILE}")


def _decorator_methods(func: ast.FunctionDef) -> set[str]:
    methods: set[str] = set()
    for dec in func.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        if not isinstance(dec.func, ast.Name) or dec.func.id != "api_view":
            continue
        if not dec.args:
            continue
        arg = dec.args[0]
        if isinstance(arg, (ast.List, ast.Tuple)):
            for elt in arg.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    methods.add(elt.value)
    return methods


def _has_counts_response(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "Response":
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if not isinstance(arg0, ast.Dict):
            continue
        for key in arg0.keys:
            if isinstance(key, ast.Constant) and key.value == "counts":
                return True
    return False


def _uses_list_response(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "list_response":
            return True
    return False


def _calls_parse_ids_payload(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "_parse_ids_payload":
            return True
    return False


def test_match_count_endpoints_accept_post_and_get() -> None:
    tree = _load_tree()
    for name in _TARGETS:
        func = _find_func(tree, name)
        methods = _decorator_methods(func)
        assert {"GET", "POST"}.issubset(
            methods
        ), f"{name} must accept GET+POST for UI compatibility, got {sorted(methods)}"


def test_match_count_endpoints_return_counts_payload() -> None:
    tree = _load_tree()
    for name in _TARGETS:
        func = _find_func(tree, name)
        assert _has_counts_response(func), f"{name} must return Response({{'counts': ...}})"
        assert not _uses_list_response(func), f"{name} must not use list_response()"
        assert _calls_parse_ids_payload(
            func
        ), f"{name} must route GET+POST through _parse_ids_payload for consistent behavior"
