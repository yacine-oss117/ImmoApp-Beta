"""
Task registry anti-regression tests.

Guarantees that all task names from the canonical enum are exported and
wired in ``server/api/tasks.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from server.api.task_names import TaskName

_TASKS_FILE = Path(__file__).parents[3] / "server" / "api" / "tasks.py"


def _parse_tree() -> ast.Module:
    source = _TASKS_FILE.read_text(encoding="utf-8")
    return ast.parse(source)


def _exported_task_names() -> set[str]:
    tree = _parse_tree()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id != "__all__":
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                return set()
            names: set[str] = set()
            for item in node.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    names.add(item.value)
            return names
    return set()


def _imported_task_names() -> set[str]:
    tree = _parse_tree()
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 1 or not node.module or not node.module.startswith("tasks_"):
            continue
        for alias in node.names:
            if alias.name != "*":
                names.add(alias.asname or alias.name)
    return names


def test_task_registry_names_are_exported() -> None:
    exported = _exported_task_names()
    missing = [name.value for name in TaskName if name.value not in exported]
    assert not missing, f"Missing task exports in server.api.tasks: {missing}"


def test_task_registry_names_are_imported() -> None:
    imported = _imported_task_names()
    for name in TaskName:
        assert name.value in imported, f"{name.value} missing import wiring in server.api.tasks"
