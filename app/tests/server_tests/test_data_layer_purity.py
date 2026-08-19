"""
Data layer purity guards (API-only).

Ensure no local DB connection helpers remain in the codebase.
"""

from __future__ import annotations

import os


def _iter_app_files() -> list[str]:
    files: list[str] = []
    for root, _, filenames in os.walk("app"):
        if "app/tests" in root.replace("\\", "/"):
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(os.path.join(root, filename))
    return files


def test_no_db_connect_helpers() -> None:
    violations: list[str] = []
    for filepath in _iter_app_files():
        rel = filepath.replace("\\", "/")
        with open(filepath, encoding="utf-8") as handle:
            content = handle.read()
        if "db_connect(" in content or "open_connection(" in content:
            violations.append(rel)

    assert (
        not violations
    ), "Local DB helpers must be removed in API-only mode.\n" "Violations found:\n" + "\n".join(
        f"  - {path}" for path in sorted(violations)
    )


def test_no_manual_connection_close() -> None:
    violations: list[str] = []
    for filepath in _iter_app_files():
        rel = filepath.replace("\\", "/")
        with open(filepath, encoding="utf-8") as handle:
            content = handle.read()
        if "conn.close(" in content:
            violations.append(rel)

    assert (
        not violations
    ), "Repositories should not close connections manually.\n" "Violations found:\n" + "\n".join(
        f"  - {path}" for path in sorted(violations)
    )
