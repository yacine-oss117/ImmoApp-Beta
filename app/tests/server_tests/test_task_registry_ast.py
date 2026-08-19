"""
Task registry guardrails.

Ensures the TaskName enum stays aligned with exported Celery tasks.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_TASKS_FILE = _REPO_ROOT / "server" / "api" / "tasks.py"
_TASK_NAMES_FILE = _REPO_ROOT / "server" / "api" / "task_names.py"


def _load_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _collect_task_exports(tree: ast.Module) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                names = {
                    elt.value
                    for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                }
                return names
    raise AssertionError(f"__all__ not found in {_TASKS_FILE}")


def _collect_task_name_values(tree: ast.Module) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "TaskName":
            values: set[str] = set()
            for item in node.body:
                if not isinstance(item, ast.Assign):
                    continue
                if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                    values.add(item.value.value)
            if values:
                return values
    raise AssertionError(f"TaskName enum not found in {_TASK_NAMES_FILE}")


def test_task_registry_matches_exported_tasks() -> None:
    tasks_tree = _load_tree(_TASKS_FILE)
    names_tree = _load_tree(_TASK_NAMES_FILE)
    exported = _collect_task_exports(tasks_tree)
    enum_values = _collect_task_name_values(names_tree)
    assert exported == enum_values, (
        "TaskName enum values must match api.tasks __all__ exports. "
        f"Only in __all__: {sorted(exported - enum_values)}. "
        f"Only in TaskName: {sorted(enum_values - exported)}."
    )
