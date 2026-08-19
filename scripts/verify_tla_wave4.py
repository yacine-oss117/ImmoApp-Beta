from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    jar = os.environ.get("TLA_TOOLS_JAR", "").strip()
    if not jar:
        print("INFO: TLA_TOOLS_JAR not set; skipping Wave-4 TLA+ verification.")
        return 0
    jar_path = Path(jar)
    if not jar_path.exists():
        print(f"INFO: TLA_TOOLS_JAR not found at {jar_path}; skipping Wave-4 TLA+ verification.")
        return 0

    spec_path = Path("tools/tla/specs/match_visibility_wave4.tla")
    cfg_path = Path("tools/tla/specs/match_visibility_wave4.cfg")
    if not spec_path.exists():
        print("ERROR: Wave-4 spec missing: tools/tla/specs/match_visibility_wave4.tla")
        return 1
    if not cfg_path.exists():
        print("ERROR: Wave-4 config missing: tools/tla/specs/match_visibility_wave4.cfg")
        return 1

    cmd = ["java", "-jar", str(jar_path), "-config", str(cfg_path), str(spec_path)]
    print("Running Wave-4 TLA+ verification:", " ".join(cmd))
    try:
        subprocess.check_call(cmd)
    except FileNotFoundError:
        print("INFO: java not found; skipping Wave-4 TLA+ verification.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: Wave-4 TLA+ verification failed with exit code {exc.returncode}")
        return exc.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
