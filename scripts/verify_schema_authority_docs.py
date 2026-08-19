from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from generate_schema_authority import render_schema_authority
from schema_authority_common import SCHEMA_AUTHORITY_OUTPUT_PATH


def main() -> int:
    if not SCHEMA_AUTHORITY_OUTPUT_PATH.exists():
        print(
            "verify_schema_authority_docs: missing docs/reference/SCHEMA_AUTHORITY.md. "
            "Run python scripts/generate_schema_authority.py"
        )
        return 1
    expected = render_schema_authority()
    current = SCHEMA_AUTHORITY_OUTPUT_PATH.read_text(encoding="utf-8")
    if current != expected:
        print(
            "verify_schema_authority_docs: docs/reference/SCHEMA_AUTHORITY.md is stale. "
            "Run python scripts/generate_schema_authority.py"
        )
        return 1
    print("verify_schema_authority_docs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
