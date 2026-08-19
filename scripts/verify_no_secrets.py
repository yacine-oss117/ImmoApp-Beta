from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

SENSITIVE_PATTERNS = (
    "JWT_SECRET",
    "DJANGO_SECRET_KEY",
    "MINIO_SECRET_KEY",
    "STORAGE_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "POSTGRES_ADMIN_PASSWORD",
    "ALE_MASTER_KEY",
    "ALE_SEARCH_SECRET",
    "BAO_TOKEN",
    "BAO_SECRET_ID",
)


PLACEHOLDER_HINTS = (
    "example",
    "changeme",
    "change-me",
    "placeholder",
    "dummy",
    "test",
    "ci-",
    "ci_",
    "nightly",
    "game-day",
    "immoapp",
    "localhost",
    "127.0.0.1",
)


def _should_enforce() -> bool:
    def _truthy(value: str | None) -> bool:
        if not value:
            return False
        return value.strip().lower() in {"1", "true", "yes", "on"}

    return _truthy(os.environ.get("CI")) or _truthy(os.environ.get("IMMOAPP_ENFORCE_NO_SECRETS"))


def _looks_like_placeholder(value: str) -> bool:
    val = value.strip().strip("'\"")
    if not val:
        return True
    if val.startswith("${") and val.endswith("}"):
        return True
    if "${{" in val and "}}" in val:
        return True
    low = val.lower()
    if "secrets." in low:
        return True
    if low in {"none", "null", "false", "0", "xxxx", "***", "****", "*****"}:
        return True
    return any(hint in low for hint in PLACEHOLDER_HINTS)


def _is_scannable_file(path: Path) -> bool:
    if path.name in {
        ".env",
        ".env.local",
        ".env.prod",
        ".env.example",
        ".env.local.example",
        ".env.prod.example",
    }:
        return False
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip"}:
        return False
    if "docs" in path.parts:
        return False
    return True


_ASSIGNMENT_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*[:=]\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _iter_files(repo_root: Path) -> list[Path]:
    skip_dirs = {
        ".git",
        ".mypy_cache",
        ".cache",
        ".venv",
        ".vscode",
        "venvs",
        "node_modules",
        "dist",
        "build",
        "ProgramData",
    }
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.is_dir():
            continue
        if not _is_scannable_file(path):
            continue
        files.append(path)
    return files


def _is_tracked(repo_root: Path, filename: str) -> bool:
    if shutil.which("git") is None:
        return False
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", filename],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def main() -> None:
    if not _should_enforce():
        print("verify_no_secrets: skipped (not in CI or enforce mode)")
        return

    repo_root = Path(__file__).resolve().parents[1]
    # Ship-mode strictness: no real env files may exist in the working tree.
    for env_name in (".env", ".env.local", ".env.prod"):
        env_path = repo_root / env_name
        if env_path.exists():
            raise SystemExit(f"verify_no_secrets: {env_name} must not exist in enforce mode.")
        tracked = _is_tracked(repo_root, env_name)
        if tracked:
            raise SystemExit(
                f"verify_no_secrets: {env_name} is tracked by git; remove and rotate secrets."
            )

    violations: list[str] = []
    for path in _iter_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = _ASSIGNMENT_RE.match(raw_line)
            if not match:
                continue
            key = match.group(1).upper()
            if key not in SENSITIVE_PATTERNS:
                continue
            value = match.group(2)
            if _looks_like_placeholder(value):
                continue
            violations.append(f"{path}:{line_no}: {key}")

    if violations:
        raise SystemExit(
            "verify_no_secrets: potential secret patterns found:\n" + "\n".join(violations)
        )

    print("verify_no_secrets: OK")


if __name__ == "__main__":
    main()
