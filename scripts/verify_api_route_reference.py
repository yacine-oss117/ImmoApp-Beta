from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from generate_api_route_reference import OUTPUT_PATH, render_api_route_reference


def main() -> int:
    if not OUTPUT_PATH.exists():
        print(
            "verify_api_route_reference: missing docs/reference/API_ROUTE_REFERENCE.md. "
            "Run python scripts/generate_api_route_reference.py"
        )
        return 1
    expected = render_api_route_reference()
    current = OUTPUT_PATH.read_text(encoding="utf-8")
    if current != expected:
        print(
            "verify_api_route_reference: docs/reference/API_ROUTE_REFERENCE.md is stale. "
            "Run python scripts/generate_api_route_reference.py"
        )
        return 1
    print("verify_api_route_reference: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
