"""
API response shape guardrails.

Ensures list endpoints return a consistent {"items": [...], "total": N} payload
when constructing Response with a dict literal containing "items".
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]


def _extract_response_dict_keys(tree: ast.AST) -> list[set[str]]:
    keys_found: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        else:
            continue
        if func_name != "Response":
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if not isinstance(arg0, ast.Dict):
            continue
        keys: set[str] = set()
        for key in arg0.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
        if keys:
            keys_found.append(keys)
    return keys_found


def test_list_responses_include_total() -> None:
    violations: list[str] = []
    for py_file in _REPO_ROOT.glob("server/api/views_*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for keys in _extract_response_dict_keys(tree):
            if "items" in keys and "total" not in keys:
                violations.append(f"{py_file.name}: Response with items missing total")
    assert not violations, (
        "API contract violation: list responses must include total.\n"
        "Use list_response(items) or include total explicitly.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )
