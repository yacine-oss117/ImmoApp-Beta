from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

FORBIDDEN_IMPORT_TARGETS = (
    ("core", "trigram_service"),
    ("server.services", "context"),
    ("server.services", "secrets_status"),
)

FORBIDDEN_IMPORT_SNIPPETS = (
    *(
        (f"from {module_name}.{symbol_name} " + "import")
        for module_name, symbol_name in FORBIDDEN_IMPORT_TARGETS
    ),
    *(
        f"import {module_name}.{symbol_name}"
        for module_name, symbol_name in FORBIDDEN_IMPORT_TARGETS
    ),
)


def _runtime_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in ("app", "server", "core"):
        root = REPO_ROOT / root_name
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in rel:
                continue
            files.append(path)
    return files


def test_removed_legacy_schema_ref_folder() -> None:
    legacy_suffix = "_legacy_schema" + "_reference"
    legacy_dir = REPO_ROOT / "server" / "pg" / legacy_suffix
    assert not legacy_dir.exists(), (
        "Legacy schema reference folder must be removed after hard cut: " f"{legacy_dir.as_posix()}"
    )


def test_runtime_modules_forbid_retired_compat_imports() -> None:
    violations: list[str] = []

    for path in _runtime_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_IMPORT_SNIPPETS:
            if snippet in source:
                violations.append(f"{rel}: contains forbidden import {snippet!r}")

    assert not violations, "Found retired compatibility imports:\n" + "\n".join(violations)
