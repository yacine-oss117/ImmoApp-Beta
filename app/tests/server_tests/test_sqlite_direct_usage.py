"""
Guardrail: sqlite3.connect usage must be removed in API-only mode.
"""

from __future__ import annotations

import os


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _iter_app_files() -> list[str]:
    files: list[str] = []
    for root, _, filenames in os.walk("app"):
        if _normalize_path(root).startswith("app/tests"):
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(os.path.join(root, filename))
    return files


def test_sqlite_connect_not_used_anywhere() -> None:
    violations: list[str] = []

    for filepath in _iter_app_files():
        rel_path = _normalize_path(os.path.relpath(filepath))

        with open(filepath, encoding="utf-8") as handle:
            content = handle.read()

        if "sqlite3.connect" in content:
            violations.append(rel_path)

    assert (
        not violations
    ), "sqlite3.connect must be removed in API-only mode.\n" "Violations found:\n" + "\n".join(
        f"  - {path}" for path in sorted(violations)
    )
