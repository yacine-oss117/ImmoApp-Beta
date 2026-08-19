from __future__ import annotations

import ast
from pathlib import Path


def _parse_mainwindow() -> tuple[ast.ClassDef, str]:
    path = Path("app/main_window.py")
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            return node, source
    raise AssertionError("MainWindow class not found in app/main_window.py")


def test_mainwindow_uses_composition_not_mixins() -> None:
    cls, _ = _parse_mainwindow()
    base_names: list[str] = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            base_names.append(base.id)
        elif isinstance(base, ast.Attribute):
            base_names.append(base.attr)
    assert "QMainWindow" in base_names
    assert not any(
        name.endswith("Mixin") for name in base_names
    ), "MainWindow should compose controllers, not inherit mixins directly."


def test_mainwindow_builds_controller_set() -> None:
    _, source = _parse_mainwindow()
    assert "MainWindowControllers.build(self)" in source


def test_mainwindow_no_dynamic_getattr_fallback() -> None:
    _, source = _parse_mainwindow()
    assert "def __getattr__(" not in source
