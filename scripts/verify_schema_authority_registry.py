from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.schema_authority_common import (
    django_models_by_label,
    django_models_by_table,
    discover_alembic_table_revisions,
    local_migration_files,
    migration_id_from_path,
)
from scripts.verify_alembic_fresh_chain import REQUIRED_TABLES
from server.pg.schema_authority_registry import iter_schema_table_contracts


def collect_registry_issues() -> list[str]:
    issues: list[str] = []
    contracts = iter_schema_table_contracts()
    by_name: dict[str, object] = {}
    django_tables = django_models_by_table()
    django_labels = django_models_by_label()
    alembic_tables = discover_alembic_table_revisions()
    local_migration_ids = {migration_id_from_path(path) for path in local_migration_files()}

    for contract in contracts:
        existing = by_name.get(contract.table_name)
        if existing is not None:
            issues.append(f"duplicate registry entry for table {contract.table_name}")
        by_name[contract.table_name] = contract

        if contract.mirror_strategy == "state_only_mirror" and contract.owner != "alembic_physical":
            issues.append(
                f"{contract.table_name}: state_only_mirror requires owner=alembic_physical"
            )
        if contract.mirror_strategy == "state_only_mirror" and not contract.orm_model:
            issues.append(f"{contract.table_name}: state_only_mirror requires orm_model")
        if contract.orm_model and contract.orm_model not in django_labels:
            issues.append(f"{contract.table_name}: orm_model {contract.orm_model} not found")
        if (
            contract.orm_model
            and contract.orm_model in django_labels
            and contract.table_name != str(django_labels[contract.orm_model]._meta.db_table)
        ):
            actual_table = str(django_labels[contract.orm_model]._meta.db_table)
            issues.append(
                f"{contract.table_name}: orm_model {contract.orm_model} maps to {actual_table}"
            )
        if (
            contract.creating_django_migration
            and ".000" in contract.creating_django_migration
            and contract.creating_django_migration not in local_migration_ids
        ):
            issues.append(
                f"{contract.table_name}: missing local migration {contract.creating_django_migration}"
            )

    for table_name in sorted(django_tables):
        if table_name not in by_name:
            issues.append(f"missing registry entry for Django model table {table_name}")

    for table_name in sorted(alembic_tables):
        if table_name not in by_name:
            issues.append(f"missing registry entry for Alembic-discovered table {table_name}")
        elif getattr(by_name[table_name], "owner", None) != "alembic_physical":
            issues.append(
                f"{table_name}: discovered in Alembic revisions but registry owner is "
                f"{getattr(by_name[table_name], 'owner', '<unknown>')}"
            )

    for table_name in REQUIRED_TABLES:
        contract = by_name.get(table_name)
        if contract is None:
            issues.append(f"{table_name}: required by fresh-chain but missing from registry")
        elif getattr(contract, "owner", None) != "alembic_physical":
            issues.append(f"{table_name}: fresh-chain table must be alembic_physical")

    return issues


def main() -> int:
    issues = collect_registry_issues()
    if issues:
        print("verify_schema_authority_registry: FAILED")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("verify_schema_authority_registry: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
