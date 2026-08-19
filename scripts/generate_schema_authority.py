from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from schema_authority_common import SCHEMA_AUTHORITY_OUTPUT_PATH, render_contract_table
from server.pg.schema_authority_registry import (
    iter_contracts_by_owner,
    iter_state_only_mirror_contracts,
    iter_schema_table_contracts,
)


def render_schema_authority() -> str:
    all_contracts = iter_schema_table_contracts()
    alembic_contracts = tuple(iter_contracts_by_owner("alembic_physical"))
    django_contracts = tuple(iter_contracts_by_owner("django_physical"))
    mirror_contracts = iter_state_only_mirror_contracts()
    lines = [
        "# Schema Authority",
        "",
        "Generated from `server/pg/schema_authority_registry.py`.",
        "Do not hand-edit this file. Rebuild it with `python scripts/generate_schema_authority.py`.",
        "",
        f"- registered contracts: {len(all_contracts)}",
        f"- Alembic physical tables: {len(alembic_contracts)}",
        f"- Django physical tables: {len(django_contracts)}",
        f"- state-only mirrors: {len(mirror_contracts)}",
        "",
        "## Locked Policy",
        "",
        "- Alembic owns physical schema truth for business tables.",
        "- Django owns runtime model state.",
        "- Django migrations must not blindly duplicate Alembic DDL.",
        "- Every mirrored ORM model must exactly match its raw-SQL/state contract.",
        "- Fresh-chain and Django model-drift checks remain mandatory release gates.",
        "",
        "## State-Only Mirror Migrations",
        "",
    ]
    lines.extend(render_contract_table(mirror_contracts))
    lines.extend(["", "## Alembic Physical Ownership", ""])
    lines.extend(render_contract_table(alembic_contracts))
    lines.extend(["", "## Django Physical Ownership", ""])
    lines.extend(render_contract_table(django_contracts))
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    SCHEMA_AUTHORITY_OUTPUT_PATH.write_text(render_schema_authority(), encoding="utf-8")
    print(
        "generate_schema_authority: wrote " f"{SCHEMA_AUTHORITY_OUTPUT_PATH.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
