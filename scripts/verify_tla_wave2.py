"""
Wave-2 TLA+ verification for tenant isolation + row_version invariants.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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


def _run_tlc(java: str, jar: Path, spec: Path, cfg: Path) -> int:
    cmd = [java, "-jar", str(jar), "-config", str(cfg), str(spec)]
    print("Running:", " ".join(cmd))
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    java = shutil.which("java")
    jar = _find_tla_jar(repo_root)
    if not java or not jar:
        print("INFO: TLA+ tools not configured; skipping Wave-2 TLC run.")
        return 0

    specs = [
        (
            repo_root / "tools" / "tla" / "specs" / "rls_isolation_wave2.tla",
            repo_root / "tools" / "tla" / "specs" / "rls_isolation_wave2.cfg",
        ),
        (
            repo_root / "tools" / "tla" / "specs" / "row_version_wave2.tla",
            repo_root / "tools" / "tla" / "specs" / "row_version_wave2.cfg",
        ),
    ]
    for spec, cfg in specs:
        if not spec.exists() or not cfg.exists():
            print(f"ERROR: Missing TLA+ spec/config: {spec} / {cfg}")
            return 1
        result = _run_tlc(java, jar, spec, cfg)
        if result != 0:
            return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
