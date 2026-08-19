from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from schema_authority_common import (
    REPO_ROOT as _COMMON_REPO_ROOT,
    django_models_by_table,
    discover_alembic_table_revisions,
    render_contract_table,
)
from scripts.repo_layout import DOCS_REFERENCE_ROOT
from server.pg.schema_authority_registry import (
    iter_contracts_by_owner,
    iter_schema_table_contracts,
)

OUTPUT_PATH = DOCS_REFERENCE_ROOT / "DB_TABLE_CATALOG.md"


def _django_tables() -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for table_name, model in django_models_by_table().items():
        meta = model._meta
        grouped[str(meta.app_label)].append((str(table_name), str(meta.object_name)))
    return {key: sorted(value) for key, value in sorted(grouped.items())}


def render_db_table_catalog() -> str:
    django_tables = _django_tables()
    alembic_revisions = discover_alembic_table_revisions()
    all_contracts = iter_schema_table_contracts()
    lines = [
        "# DB Table Catalog",
        "",
        "Generated from the canonical schema authority registry, live Django model metadata,",
        "and Alembic revision discovery.",
        "Do not hand-edit this file. Rebuild it with `python scripts/generate_db_table_catalog.py`.",
        "",
        f"- registered schema contracts: {len(all_contracts)}",
        f"- Django model tables: {sum(len(items) for items in django_tables.values())}",
        f"- Alembic-created tables discovered from revisions: {len(alembic_revisions)}",
        "",
        "Use `SCHEMA_AUTHORITY.md` for the ownership contract, `DB_SCHEMA_REFERENCE.md` for the",
        "human-oriented domain view, and `DB_MIGRATION_STRATEGY.md` for authoring rules.",
        "",
        "## Authority Summary",
        "",
    ]
    lines.extend(render_contract_table(all_contracts))
    lines.extend(["", "## Django Runtime Models", ""])
    for app_label, items in django_tables.items():
        lines.extend([f"### {app_label}", "", "| Table | Model |", "| --- | --- |"])
        for table_name, model_name in items:
            lines.append(f"| `{table_name}` | `{model_name}` |")
        lines.append("")

    lines.extend(["## Alembic Physical Tables", ""])
    lines.extend(render_contract_table(tuple(iter_contracts_by_owner("alembic_physical"))))
    lines.extend(["", "## Django Physical Tables", ""])
    lines.extend(render_contract_table(tuple(iter_contracts_by_owner("django_physical"))))
    lines.extend(["", "## Alembic Discovery", "", "| Table | Revisions |", "| --- | --- |"])
    for table_name in sorted(alembic_revisions):
        revisions = ", ".join(f"`{revision}`" for revision in sorted(alembic_revisions[table_name]))
        lines.append(f"| `{table_name}` | {revisions} |")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    OUTPUT_PATH.write_text(render_db_table_catalog(), encoding="utf-8")
    print(f"generate_db_table_catalog: wrote {OUTPUT_PATH.relative_to(_COMMON_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
