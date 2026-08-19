"""
Portability guards to keep matcher DB-agnostic.

These tests intentionally fail if matcher drifts back to sqlite3.Connection
or if services start passing session.connection into matcher again.
"""

from __future__ import annotations

import ast
from pathlib import Path

MATCHER_DIR = Path(__file__).parent.parent / "matcher"
SERVICES_DIR = Path(__file__).parent.parent / "services"


def _py_files(base: Path) -> list[Path]:
    return list(base.rglob("*.py")) if base.exists() else []


def test_matcher_does_not_import_sqlite3() -> None:
    """Verify that no file in app/matcher imports sqlite3."""
    for f in _py_files(MATCHER_DIR):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert (
                        alias.name != "sqlite3"
                    ), f"{f} imports sqlite3 (matcher must be DB-agnostic)"
            if isinstance(node, ast.ImportFrom):
                assert (
                    node.module != "sqlite3"
                ), f"{f} imports from sqlite3 (matcher must be DB-agnostic)"


def test_matcher_does_not_reference_sqlite3_connection_typehint() -> None:
    """Verify that no file in app/matcher mentions sqlite3.Connection."""
    for f in _py_files(MATCHER_DIR):
        text = f.read_text(encoding="utf-8")
        assert (
            "sqlite3.Connection" not in text
        ), f"{f} references sqlite3.Connection (typehint must be DbSession)"


def test_services_do_not_pass_session_connection_into_matcher_calls() -> None:
    """
    Heuristic guard: forbid Attribute(session, "connection") used as argument in matcher calls.
    Keeps the intended boundary: services pass session (DbSession) into matcher.
    """
    for f in _py_files(SERVICES_DIR):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Look for any argument of the form: session.connection
            for arg in node.args:
                if (
                    isinstance(arg, ast.Attribute)
                    and arg.attr == "connection"
                    and isinstance(arg.value, ast.Name)
                ):
                    # Only fail if the call is to matcher.* or imported matcher functions
                    # (loose but effective)
                    func_src = (
                        ast.get_source_segment(f.read_text(encoding="utf-8"), node.func) or ""
                    )
                    if "matcher." in func_src or "match_" in func_src:
                        raise AssertionError(
                            f"{f.name}: matcher call passes '{arg.value.id}.connection'; pass the session instead"
                        )
