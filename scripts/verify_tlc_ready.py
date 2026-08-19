from __future__ import annotations

import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _exists(path: str | None) -> bool:
    return bool(path and Path(path).expanduser().exists())


def _find_java_executable() -> Path | None:
    java_cmd = shutil.which("java")
    if java_cmd:
        return Path(java_cmd)

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        from_java_home = Path(java_home) / "bin" / "java.exe"
        if from_java_home.exists():
            return from_java_home

    roots = (
        Path("C:/Program Files/Eclipse Adoptium"),
        Path("C:/Program Files/Java"),
    )
    for root in roots:
        if not root.exists():
            continue
        hits = sorted(root.rglob("java.exe"), key=lambda p: str(p), reverse=True)
        for hit in hits:
            if str(hit).lower().endswith("\\bin\\java.exe"):
                return hit
    return None


def main() -> None:
    jar_env = os.environ.get("TLA_TOOLS_JAR")
    jar_repo = REPO_ROOT / "tools" / "tla" / "tla2tools.jar"

    jar_ready = _exists(jar_env) or jar_repo.exists()
    java_bin = _find_java_executable()
    java_ready = java_bin is not None

    if not jar_ready or not java_ready:
        missing: list[str] = []
        if not jar_ready:
            missing.append("TLA jar")
        if not java_ready:
            missing.append("Java")
        raise SystemExit("verify_tlc_ready: missing " + ", ".join(missing))

    resolved_jar = str(jar_env) if _exists(jar_env) else str(jar_repo)
    resolved_java = str(java_bin)
    print("verify_tlc_ready: OK")
    print(f"jar={resolved_jar}")
    print(f"java={resolved_java}")


if __name__ == "__main__":
    main()
