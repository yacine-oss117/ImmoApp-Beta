"""Guardrail: legacy importer compatibility modules must stay retired."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_MODULES = {
    "core.importer.engine",
    "core.importer.transform.context",
    "core.importer.transform.row_transformer",
    "core.importer.transform.validator",
}
FORBIDDEN_FILES = {
    ROOT / "core/importer/engine.py",
    ROOT / "core/importer/transform/context.py",
    ROOT / "core/importer/transform/row_transformer.py",
    ROOT / "core/importer/transform/validator.py",
}


def test_legacy_compat_files_removed() -> None:
    existing = [str(path.relative_to(ROOT)) for path in FORBIDDEN_FILES if path.exists()]
    assert not existing, "Legacy importer compatibility files must not exist:\n" + "\n".join(
        f"  - {path}" for path in sorted(existing)
    )


def test_no_forbidden_imports_remaining() -> None:
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT)
        if _should_skip(rel):
            continue
        source = py_file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(rel))
        violations.extend(_scan_imports(tree, str(rel)))

    assert not violations, "Found forbidden legacy importer imports:\n" + "\n".join(
        f"  - {item}" for item in sorted(violations)
    )


def _scan_imports(tree: ast.AST, rel_path: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if _matches_forbidden(name):
                    violations.append(f"{rel_path}: import {name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                continue
            if _matches_forbidden(module):
                violations.append(f"{rel_path}: from {module} import ...")
    return violations


def _matches_forbidden(module_name: str) -> bool:
    return any(
        module_name == forbidden or module_name.startswith(f"{forbidden}.")
        for forbidden in FORBIDDEN_MODULES
    )


def _should_skip(rel: Path) -> bool:
    text = str(rel).replace("\\", "/")
    return (
        text.startswith(".git/")
        or text.startswith(".venv/")
        or text.startswith("venv/")
        or text.startswith("__pycache__/")
    )
