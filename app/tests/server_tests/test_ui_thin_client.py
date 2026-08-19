"""
Thin-UI guardrails.

Client services should not embed business validation logic; the server is the source of truth.
"""

from __future__ import annotations

import os


def _iter_service_files() -> list[str]:
    files: list[str] = []
    for root, _, filenames in os.walk("app/services"):
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(os.path.join(root, filename))
    return files


def test_services_do_not_embed_validation_helpers() -> None:
    violations: list[str] = []
    for filepath in _iter_service_files():
        rel = filepath.replace("\\", "/")
        with open(filepath, encoding="utf-8") as handle:
            content = handle.read()
        if "coerce_number(" in content or "ensure_min_le_max(" in content:
            violations.append(rel)

    assert not violations, (
        "Client services must not embed business validation helpers.\n"
        "Violations found:\n" + "\n".join(f"  - {path}" for path in sorted(violations))
    )
