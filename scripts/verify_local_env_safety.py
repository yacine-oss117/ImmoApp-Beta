from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _assert_gitignore_has_env(repo_root: Path) -> None:
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        raise SystemExit("verify_local_env_safety: .gitignore is missing.")
    lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
    required = {".env", ".env.local", ".env.prod"}
    missing = sorted(required - lines)
    if missing:
        raise SystemExit(
            "verify_local_env_safety: .gitignore must contain "
            + ", ".join(f"'{item}'" for item in missing)
            + "."
        )


def _is_env_tracked(repo_root: Path, filename: str) -> bool:
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
    repo_root = Path(__file__).resolve().parents[1]
    _assert_gitignore_has_env(repo_root)

    for filename in (".env", ".env.local", ".env.prod"):
        env_path = repo_root / filename
        if env_path.exists() and _is_env_tracked(repo_root, filename):
            raise SystemExit(
                f"verify_local_env_safety: {filename} is tracked by git. Keep env files local only."
            )

    print("verify_local_env_safety: OK")


if __name__ == "__main__":
    main()
