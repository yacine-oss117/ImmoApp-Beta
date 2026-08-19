"""
Wave-1 TLA+ verification for match cache correctness.

This runs TLC if the TLA+ tools JAR is available. If not, it prints a warning
and exits successfully (so local dev isn't blocked).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_tla_jar(repo_root: Path) -> Path | None:
    env_path = os.environ.get("TLA_TOOLS_JAR")
    if env_path:
        jar = Path(env_path)
        if jar.exists():
            return jar
    candidates = [
        repo_root / "tools" / "tla" / "tla2tools.jar",
        repo_root / "tla2tools.jar",
    ]
    for jar in candidates:
        if jar.exists():
            return jar
    return None


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    java = shutil.which("java")
    jar = _find_tla_jar(repo_root)
    if not java or not jar:
        print("INFO: TLA+ tools not configured; skipping Wave-1 TLC run.")
        return 0

    spec = repo_root / "tools" / "tla" / "specs" / "match_cache_wave1.tla"
    cfg = repo_root / "tools" / "tla" / "specs" / "match_cache_wave1.cfg"
    if not spec.exists() or not cfg.exists():
        print("ERROR: TLA+ spec/config missing.")
        return 1

    cmd = [java, "-jar", str(jar), "-config", str(cfg), str(spec)]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
