from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.schema_authority_common import (
    django_models_by_label,
    load_migration_class,
    local_migration_files,
    migration_id_from_path,
)
from server.pg.schema_authority_registry import schema_table_contracts_by_name

_PHYSICAL_DDL_OPERATION_TYPES = {
    "CreateModel",
    "DeleteModel",
    "AddField",
    "RemoveField",
    "AlterField",
    "RenameField",
    "RenameModel",
    "AddIndex",
    "RemoveIndex",
    "AddConstraint",
    "RemoveConstraint",
}


def _default_table_name(app_label: str, model_name: str) -> str:
    return f"{app_label}_{model_name.lower()}"


def _table_name_for_operation(*, app_label: str, operation: Any) -> str | None:
    models_by_label = django_models_by_label()
    lower_models_by_label = {label.lower(): model for label, model in models_by_label.items()}
    class_name = operation.__class__.__name__
    if class_name == "CreateModel":
        model_label = f"{app_label}.{operation.name}"
        model = models_by_label.get(model_label)
        if model is not None:
            return str(model._meta.db_table)
        return _default_table_name(app_label, operation.name)
    model_name = getattr(operation, "model_name", None)
    if not model_name:
        return None
    model_label = f"{app_label}.{str(model_name)}".lower()
    model = lower_models_by_label.get(model_label)
    if model is not None:
        return str(model._meta.db_table)
    return _default_table_name(app_label, str(model_name))


def collect_blind_ddl_issues_for_operations(
    *,
    migration_id: str,
    app_label: str,
    operations: list[Any],
) -> list[str]:
    issues: list[str] = []
    contracts = schema_table_contracts_by_name()

    def visit(operation: Any, *, context: str) -> None:
        class_name = operation.__class__.__name__
        if class_name == "SeparateDatabaseAndState":
            for nested in getattr(operation, "database_operations", []):
                visit(nested, context="database")
            for nested in getattr(operation, "state_operations", []):
                visit(nested, context="state")
            return

        if class_name not in _PHYSICAL_DDL_OPERATION_TYPES:
            return
        table_name = _table_name_for_operation(app_label=app_label, operation=operation)
        if not table_name:
            return
        contract = contracts.get(table_name)
        if contract is None or contract.owner != "alembic_physical":
            return
        if context == "state":
            return
        issues.append(
            f"{migration_id}: {class_name} on Alembic-owned table {table_name} "
            "must live in SeparateDatabaseAndState.state_operations only"
        )

    for operation in operations:
        visit(operation, context="plain")
    return issues


def collect_repo_blind_ddl_issues() -> list[str]:
    issues: list[str] = []
    for path in local_migration_files():
        migration_class = load_migration_class(path)
        migration_id = migration_id_from_path(path)
        app_label = migration_id.split(".", 1)[0]
        operations = list(getattr(migration_class, "operations", []))
        issues.extend(
            collect_blind_ddl_issues_for_operations(
                migration_id=migration_id,
                app_label=app_label,
                operations=operations,
            )
        )
    return issues


def main() -> int:
    issues = collect_repo_blind_ddl_issues()
    if issues:
        print("verify_no_blind_django_ddl_for_alembic_owned_tables: FAILED")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("verify_no_blind_django_ddl_for_alembic_owned_tables: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
