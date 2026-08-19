from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.hub_manager_access_client import (  # noqa: E402
    HubManagerAccessClientError,
    fetch_owner_state,
)


def _unavailable_payload(reason_code: str) -> dict[str, Any]:
    return {
        "kind": "immoapp_hub_manager_owner_state",
        "schema_version": 1,
        "state": "owner_account_missing",
        "setup_available": False,
        "activation_available": False,
        "reason_code": reason_code,
        "active_owner_admin_count": 0,
        "pending_registration_count": 0,
        "approved_registration_count": 0,
        "inactive_owner_count": 0,
        "source": "hub_db",
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve Hub Manager owner state.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("IMMOAPP_HUB_FRONT_DOOR_URL", ""),
        help="Running Hub front-door URL.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if not str(args.base_url).strip():
            raise HubManagerAccessClientError("owner_state_hub_connection_missing")
        payload = fetch_owner_state(str(args.base_url))
    except HubManagerAccessClientError as exc:
        payload = _unavailable_payload(exc.reason_code)
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    return 1 if str(payload.get("reason_code", "")).startswith("owner_state_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
