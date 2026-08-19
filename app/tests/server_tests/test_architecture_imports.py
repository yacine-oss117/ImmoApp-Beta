"""
Architecture import guard tests.

These tests enforce the repository dependency-direction rules and the
current architecture invariants:

LAYER RULES:
1. UI (views/widgets/workers) → may import ONLY app.services (plus UI libs)
   UI MUST NOT import core.data directly.
2. services → may import core.matcher and core.data, owns transactions.
   services MUST NOT import PySide6 or UI modules.
3. matcher → MUST NOT import app.services or UI modules.
4. data → MUST NOT import app.services or UI modules.

Violations will cause test failures to prevent regression.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]

_API_PG_IMPORT_ALLOWLIST = {
    "server/api/secured_view.py",
    "server/api/tasks_core.py",
}


def _get_python_files(subdir: str) -> list[Path]:
    """Get all Python files under repo root/{subdir}/."""
    base_dir = _REPO_ROOT / subdir
    if not base_dir.exists():
        return []
    return list(base_dir.rglob("*.py"))


def _extract_imports(file_path: Path) -> list[str]:
    """Extract all import module names from a Python file using AST."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


# =============================================================================
# MATCHER LAYER TESTS
# =============================================================================


def test_matcher_does_not_import_services() -> None:
    """Ensure no file in core/matcher/ imports from app.services."""
    violations: list[str] = []

    for py_file in _get_python_files("core/matcher"):
        imports = _extract_imports(py_file)
        for imp in imports:
            if imp.startswith("app.services"):
                violations.append(f"{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: core/matcher/ must not import app/services/.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_matcher_does_not_import_ui() -> None:
    """Ensure no file in core/matcher/ imports PySide6 or UI modules."""
    forbidden = ("PySide6", "app.views", "app.widgets", "app.workers")
    violations: list[str] = []

    for py_file in _get_python_files("core/matcher"):
        imports = _extract_imports(py_file)
        for imp in imports:
            if any(imp.startswith(f) for f in forbidden):
                violations.append(f"{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: core/matcher/ must not import UI modules.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


# =============================================================================
# DATA LAYER TESTS
# =============================================================================


def test_data_does_not_import_services() -> None:
    """Ensure no file in core/data/ imports from app.services."""
    violations: list[str] = []

    for py_file in _get_python_files("core/data"):
        imports = _extract_imports(py_file)
        for imp in imports:
            if imp.startswith("app.services"):
                violations.append(f"{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: core/data/ must not import app/services/.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_data_does_not_import_ui() -> None:
    """Ensure no file in core/data/ imports PySide6 or UI modules."""
    forbidden = ("PySide6", "app.views", "app.widgets", "app.workers")
    violations: list[str] = []

    for py_file in _get_python_files("core/data"):
        imports = _extract_imports(py_file)
        for imp in imports:
            if any(imp.startswith(f) for f in forbidden):
                violations.append(f"{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: core/data/ must not import UI modules.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


# =============================================================================
# UI LAYER TESTS (D1)
# =============================================================================


def test_ui_does_not_import_data() -> None:
    """Ensure UI layer (views/widgets/workers) does NOT import core.data directly."""
    violations: list[str] = []

    for subdir in ("views", "widgets", "workers"):
        for py_file in _get_python_files(f"app/{subdir}"):
            imports = _extract_imports(py_file)
            for imp in imports:
                if imp.startswith("core.data"):
                    violations.append(f"{subdir}/{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: UI layer must not import core.data/ directly.\n"
        "UI must import from app.services instead.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_ui_does_not_import_matcher() -> None:
    """Ensure UI layer (views/widgets/workers) does NOT import core.matcher directly."""
    violations: list[str] = []

    for subdir in ("views", "widgets", "workers"):
        for py_file in _get_python_files(f"app/{subdir}"):
            imports = _extract_imports(py_file)
            for imp in imports:
                if imp.startswith("core.matcher"):
                    violations.append(f"{subdir}/{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: UI layer must not import core.matcher/ directly.\n"
        "UI must import from app.services instead.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


# =============================================================================
# SERVICES LAYER TESTS (D2)
# =============================================================================


def test_services_does_not_import_ui() -> None:
    """Ensure services layer does NOT import PySide6 or UI modules."""
    forbidden = ("PySide6", "app.views", "app.widgets", "app.workers")
    violations: list[str] = []

    for py_file in _get_python_files("app/services"):
        imports = _extract_imports(py_file)
        for imp in imports:
            if any(imp.startswith(f) for f in forbidden):
                violations.append(f"{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: app/services/ must not import UI modules or PySide6.\n"
        "Services must be usable in a server context (no Qt dependencies).\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


# =============================================================================
# API LAYER TESTS (D3)
# =============================================================================


def test_api_layer_does_not_import_ui() -> None:
    """Ensure server/api does NOT import UI modules or PySide6."""
    forbidden = ("PySide6", "app.views", "app.widgets", "app.workers", "app.main")
    violations: list[str] = []

    for py_file in _get_python_files("server/api"):
        imports = _extract_imports(py_file)
        for imp in imports:
            if any(imp.startswith(f) for f in forbidden):
                violations.append(f"{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: server/api must not import UI modules.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_api_layer_does_not_import_data_layer() -> None:
    """Ensure HTTP API view entrypoints do not import data-layer modules directly."""
    forbidden = ("pg", "server.pg", "core.data")
    violations: list[str] = []

    for py_file in _get_python_files("server/api"):
        if not (py_file.name.startswith("views_") or py_file.name in {"views.py", "auth_views.py"}):
            continue
        imports = _extract_imports(py_file)
        for imp in imports:
            if any(imp == f or imp.startswith(f + ".") for f in forbidden):
                violations.append(f"{py_file.name}: imports {imp}")

    assert not violations, (
        "Architecture violation: HTTP API views must not import pg or core.data directly.\n"
        "Views should call server.services instead.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_api_pg_imports_stay_on_explicit_infra_allowlist() -> None:
    """Allow low-level DB context imports only in approved HTTP/context bridge modules."""
    forbidden = ("pg", "server.pg")
    violations: set[str] = set()

    for py_file in _get_python_files("server/api"):
        is_http_entry = py_file.name.startswith("views_") or py_file.name in {
            "views.py",
            "auth_views.py",
        }
        is_context_bridge = py_file.name in {"secured_view.py", "tasks_core.py"}
        if not (is_http_entry or is_context_bridge):
            continue
        rel = py_file.relative_to(_REPO_ROOT).as_posix()
        imports = _extract_imports(py_file)
        for imp in imports:
            if not any(imp == f or imp.startswith(f + ".") for f in forbidden):
                continue
            if rel not in _API_PG_IMPORT_ALLOWLIST:
                violations.add(f"{rel}: imports {imp}")

    assert not violations, (
        "Architecture violation: direct pg imports in API views/context bridge code "
        "must be explicitly allowlisted.\n"
        "If this import is infrastructure glue, add the file to _API_PG_IMPORT_ALLOWLIST.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in sorted(violations))
    )


def test_matcher_no_db_connect() -> None:
    """
    Ensure core/matcher/ does not use db_connect() or import core.data.db_core.
    Matcher must be pure logic receiving connections injected.
    """
    violations: list[str] = []

    # Check imports
    for py_file in _get_python_files("core/matcher"):
        imports = _extract_imports(py_file)
        for imp in imports:
            if imp == "core.data.db_core" or imp.endswith(".db_connect"):
                violations.append(f"{py_file.name}: imports {imp}")

        # Simple string search for db_connect() usage (covers aliased imports too broadly but safe)
        try:
            content = py_file.read_text(encoding="utf-8")
            if "db_connect(" in content:
                violations.append(f"{py_file.name}: calls db_connect()")
        except Exception:
            pass

    assert not violations, (
        "Architecture violation: Matcher must not open DB connections.\n"
        "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
    )


# =============================================================================
# CORE LAYER TESTS (D4)
# =============================================================================


def test_core_does_not_import_django() -> None:
    """Ensure core/ is Django-free (no django/rest_framework/channels imports)."""
    forbidden = ("django", "rest_framework", "channels")
    violations: list[str] = []

    for py_file in _get_python_files("core"):
        imports = _extract_imports(py_file)
        for imp in imports:
            if any(imp.startswith(f) for f in forbidden):
                violations.append(f"{py_file.name}: imports {imp}")

    assert (
        not violations
    ), "Architecture violation: core/ must be Django-free.\n" "Violations found:\n" + "\n".join(
        f"  - {v}" for v in violations
    )
