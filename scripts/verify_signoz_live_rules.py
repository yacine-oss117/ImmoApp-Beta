from __future__ import annotations

import os
import subprocess
import sys

from repo_layout import SIGNOZ_ALERTS_CONFIG


def _is_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _has_auth_env() -> bool:
    if os.environ.get("SIGNOZ_API_KEY"):
        return True
    return bool(
        os.environ.get("SIGNOZ_EMAIL")
        and os.environ.get("SIGNOZ_PASSWORD")
        and os.environ.get("SIGNOZ_ORG_ID")
    )


def main() -> None:
    enforce = _is_truthy(os.environ.get("IMMOAPP_ENFORCE_SIGNOZ_LIVE"))
    signoz_url = os.environ.get("SIGNOZ_URL", "").strip()

    if not signoz_url or not _has_auth_env():
        if enforce:
            raise SystemExit(
                "verify_signoz_live_rules: SIGNOZ_URL and auth env are required in enforce mode."
            )
        print("verify_signoz_live_rules: skipped (missing SIGNOZ_URL/auth env)")
        return

    args = [
        sys.executable,
        "scripts/provision_signoz_alerts.py",
        "--dry-run",
        "--config",
        str(SIGNOZ_ALERTS_CONFIG),
    ]
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        details = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        raise SystemExit(
            f"verify_signoz_live_rules: failed (exit code {result.returncode})\n{details}"
        )
    print("verify_signoz_live_rules: OK")


if __name__ == "__main__":
    main()
