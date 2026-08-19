"""
Portability guard tests for DB-agnostic layers.

These tests enforce:
1) sqlite3 is not used anywhere in the app.
2) services avoid direct `.connection` usage (pass DbSession instead).
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).parent.parent
SERVICES_DIR = APP_DIR / "services"


def _py_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]


def _imports_sqlite3(file_path: Path) -> bool:
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlite3":
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "sqlite3":
                return True
    return False


def test_no_sqlite3_imports_outside_allowed_layers() -> None:
    """Ensure sqlite3 is not imported anywhere in the app."""
    violations: list[str] = []
    for py_file in _py_files(APP_DIR):
        rel = py_file.relative_to(APP_DIR)
        if _imports_sqlite3(py_file):
            violations.append(rel.as_posix())

    assert not violations, (
        "Portability violation: sqlite3 import outside allowed layers.\n"
        "Allowed: none (API-only mode).\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_services_do_not_use_connection_attribute() -> None:
    """Ensure services avoid direct `.connection` usage for portability."""
    violations: list[str] = []
    for py_file in _py_files(SERVICES_DIR):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "connection":
                rel = py_file.relative_to(APP_DIR)
                violations.append(f"{rel.as_posix()}: uses '.connection'")

    assert not violations, (
        "Portability violation: services should pass DbSession, not session.connection.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )
