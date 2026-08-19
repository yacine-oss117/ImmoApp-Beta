from __future__ import annotations

import os
import subprocess
import sys


def _is_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    enforce = _is_truthy(os.environ.get("IMMOAPP_ENFORCE_SAST")) or _is_truthy(os.environ.get("CI"))
    args = [
        sys.executable,
        "-m",
        "bandit",
        "-q",
        "-r",
        "server",
        "core",
        "-x",
        "server/accounts/migrations",
        "-lll",
        "-ii",
    ]
    try:
        result = subprocess.run(args, check=False, capture_output=True, text=True)
    except Exception as exc:
        if enforce:
            raise SystemExit(f"verify_sast: failed to execute bandit: {exc}") from exc
        print(f"verify_sast: skipped ({exc})")
        return

    missing_bandit = "No module named bandit" in (result.stderr or "")
    if missing_bandit:
        if enforce:
            raise SystemExit("verify_sast: bandit is required when enforce mode is enabled.")
        print("verify_sast: skipped (bandit not installed)")
        return

    if result.returncode != 0:
        details = (result.stdout or "") + "\n" + (result.stderr or "")
        raise SystemExit(f"verify_sast: failed (exit code {result.returncode})\n{details.strip()}")
    print("verify_sast: OK")


if __name__ == "__main__":
    main()
