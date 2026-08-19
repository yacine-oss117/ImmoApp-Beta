from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.schema_authority_common import (
    django_models_by_label,
    iter_state_only_mirror_contracts,
    load_migration_class,
    local_migration_files,
    migration_id_from_path,
)


def _migration_class_by_id() -> dict[str, type[Any]]:
    return {
        migration_id_from_path(path): load_migration_class(path) for path in local_migration_files()
    }


def collect_state_only_mirror_issues() -> list[str]:
    issues: list[str] = []
    grouped_contracts: dict[str, list[object]] = defaultdict(list)
    models_by_label = django_models_by_label()
    migrations_by_id = _migration_class_by_id()

    for contract in iter_state_only_mirror_contracts():
        if contract.creating_django_migration:
            grouped_contracts[contract.creating_django_migration].append(contract)

    for migration_id, contracts in sorted(grouped_contracts.items()):
        migration_class = migrations_by_id.get(migration_id)
        if migration_class is None:
            issues.append(f"{migration_id}: migration file not found")
            continue
        operations = list(getattr(migration_class, "operations", []))
        if not operations:
            issues.append(f"{migration_id}: migration has no operations")
            continue
        if any(
            operation.__class__.__name__ != "SeparateDatabaseAndState" for operation in operations
        ):
            issues.append(
                f"{migration_id}: state-only mirror migrations must use SeparateDatabaseAndState only"
            )
            continue

        state_model_names: set[str] = set()
        for operation in operations:
            for db_operation in getattr(operation, "database_operations", []):
                if db_operation.__class__.__name__ != "RunSQL":
                    issues.append(
                        f"{migration_id}: database_operations must use RunSQL bridge ops only"
                    )
            for state_operation in getattr(operation, "state_operations", []):
                if state_operation.__class__.__name__ == "CreateModel":
                    state_model_names.add(str(state_operation.name))

        for contract in contracts:
            if not contract.orm_model:
                issues.append(f"{migration_id}: {contract.table_name} missing orm_model")
                continue
            model = models_by_label.get(contract.orm_model)
            if model is None:
                issues.append(f"{migration_id}: orm model {contract.orm_model} not found")
                continue
            if model.__name__ not in state_model_names:
                issues.append(
                    f"{migration_id}: expected CreateModel state op for {contract.orm_model}"
                )

    return issues


def main() -> int:
    issues = collect_state_only_mirror_issues()
    if issues:
        print("verify_state_only_mirror_contract: FAILED")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("verify_state_only_mirror_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
