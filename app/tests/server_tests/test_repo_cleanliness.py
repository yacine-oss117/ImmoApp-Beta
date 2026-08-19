"""
Guard test to ensure the repository stays clean of runtime files and tool caches.
"""

import os
import shutil
from pathlib import Path


def test_repo_is_clean() -> None:
    """
    Fail if any runtime artifacts exist in the repository tree.
    """
    repo_root = Path(__file__).resolve().parents[3]

    for cache_dir in repo_root.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)
    for pyc_file in repo_root.rglob("*.pyc"):
        try:
            pyc_file.unlink()
        except FileNotFoundError:
            continue

    violations = []

    # Directories explicitly allowed at the root
    allowed_at_root = {
        ".git",
        ".cache",
        ".github",
        "app",
        "core",
        "deployment",
        "docs",
        "ops",
        "requirements",
        "scripts",
        "server",
        "tests",
        "tools",
        ".venv",
        "Microsoft",
    }
    allowed_microsoft_dirs = {
        Path("Microsoft"),
        Path("Microsoft/Windows"),
        Path("Microsoft/Windows/PowerShell"),
    }
    allowed_microsoft_files = {
        Path("Microsoft/Windows/PowerShell/ModuleAnalysisCache"),
    }
    forbidden_hidden_at_root = {
        ".agent",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".vscode",
    }

    # Check for illegal directories/files explicitly by name/pattern
    for root, dirs, files in os.walk(repo_root):
        rel_root = Path(root).relative_to(repo_root)

        # Guard: Root folder check (catch mangled cache names like "ProgramData...")
        if rel_root == Path("."):
            for d in dirs:
                if d in forbidden_hidden_at_root:
                    violations.append(f"Forbidden hidden directory at root: {d}")
                elif d not in allowed_at_root and not d.startswith("."):
                    violations.append(f"Illegal unknown directory at root: {d}")

        # Skip .git and .venv
        if ".git" in rel_root.parts or ".venv" in rel_root.parts:
            continue

        for d in dirs:
            p = rel_root / d
            if "Microsoft" in p.parts and p not in allowed_microsoft_dirs:
                violations.append(f"Illegal Microsoft-generated directory: {p}")
            # Match illegal patterns
            if d == "__pycache__":
                violations.append(f"Illegal directory: {p}")

            # Tool caches are ONLY allowed at the root (never in subfolders)
            if d in {".ruff_cache", ".pytest_cache", ".mypy_cache"} and rel_root != Path("."):
                violations.append(f"Illegal directory: {p}")

            if str(p).replace("\\", "/") == "app/media":
                violations.append(f"Illegal directory: {p}")
            if str(p).replace("\\", "/") == "logs":
                violations.append(f"Illegal directory: {p}")

        for f in files:
            p = rel_root / f
            if "Microsoft" in p.parts and p not in allowed_microsoft_files:
                violations.append(f"Illegal Microsoft-generated file: {p}")
            if f.endswith(".pyc") or f == ".coverage":
                violations.append(f"Illegal file: {p}")
            # Database files in root or app/
            if (f.endswith(".sqlite") or f.endswith(".db")) and (
                rel_root == Path(".") or "app" in rel_root.parts
            ):
                # Filter out test fixtures if any (none currently known to be .sqlite)
                violations.append(f"Illegal database file: {p}")

    assert not violations, "Repository cleanliness violations found:\n" + "\n".join(violations)
