from __future__ import annotations

import argparse
import json
import sys

from app.tests.e2e_desktop import backend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate native desktop E2E backend identity.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    try:
        result = backend.ensure_backend_ready(args.base_url, timeout=args.timeout)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = {
        "base_url": result.base_url,
        "expected_code_identity": result.expected_code_identity,
        "actual_code_identity": (
            (result.actual_identity or {}).get("code_identity") if result.actual_identity else None
        ),
        "actual_build_identity": (
            (result.actual_identity or {}).get("build_identity") if result.actual_identity else None
        ),
        "e2e_test_mode": (result.actual_identity or {}).get("e2e_test_mode"),
        "runtime_source_mode": (result.actual_identity or {}).get("runtime_source_mode"),
        "route_presence": (result.actual_identity or {}).get("route_presence"),
        "missing_routes": list(result.missing_routes),
        "identity_match": result.identity_match,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
