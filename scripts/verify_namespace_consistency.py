from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_SKIP_DIRS = {".git", ".venv", "venvs", "__pycache__", ".mypy_cache", ".pytest_cache", "docs"}

_FORBIDDEN_PATTERNS = (
    re.compile(r"\bfrom\s+api\.", re.MULTILINE),
    re.compile(r"\bimport\s+api\b", re.MULTILINE),
    re.compile(r"\bfrom\s+immoapp_server\.", re.MULTILINE),
    re.compile(r'include\("api\.urls"\)'),
)

_FORBIDDEN_SETTINGS_MODULE = (
    'DJANGO_SETTINGS_MODULE", "immoapp_server.settings"',
    "DJANGO_SETTINGS_MODULE', 'immoapp_server.settings'",
)

_ALLOWLIST_FILES = {
    "scripts/verify_namespace_consistency.py",
}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def main() -> None:
    violations: list[str] = []
    for path in _iter_python_files():
        rel = path.relative_to(REPO_ROOT)
        rel_str = str(rel).replace("\\", "/")
        if rel_str in _ALLOWLIST_FILES:
            continue
        text = path.read_text(encoding="utf-8")

        for bad in _FORBIDDEN_SETTINGS_MODULE:
            if bad in text:
                violations.append(
                    f"{rel}: must use DJANGO_SETTINGS_MODULE=server.immoapp_server.settings"
                )

        if str(rel).startswith("server/"):
            for pattern in _FORBIDDEN_PATTERNS:
                if pattern.search(text):
                    violations.append(
                        f"{rel}: forbidden import namespace pattern '{pattern.pattern}'"
                    )

    if violations:
        raise SystemExit(
            "verify_namespace_consistency failed:\n" + "\n".join(f" - {v}" for v in violations)
        )

    print("verify_namespace_consistency: OK")


if __name__ == "__main__":
    main()
