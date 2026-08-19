from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _iter_client_runtime_files() -> list[Path]:
    files: list[Path] = []
    for root_name in ("app/services", "app/utils", "app/widgets", "app/views"):
        root = REPO_ROOT / root_name
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in rel:
                continue
            files.append(path)
    return files


def test_client_runtime_does_not_import_server_modules() -> None:
    violations: list[str] = []
    for path in _iter_client_runtime_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        content = path.read_text(encoding="utf-8")
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line.startswith("from server.") or line.startswith("import server."):
                violations.append(f"{rel}: {line}")
    assert not violations, "Client runtime modules must not import server.* modules.\n" + "\n".join(
        sorted(violations)
    )
