from __future__ import annotations

import sys
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


def _normalize_default(value: Any) -> Any:
    if callable(value):
        return getattr(value, "__name__", repr(value))
    return value


def _normalize_related_model(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.lower()
    label = getattr(getattr(value, "_meta", None), "label", None)
    if label:
        return str(label).lower()
    return str(value).lower()


def _field_contract_issues(
    *, expected_field: Any, actual_field: Any, field_label: str
) -> list[str]:
    issues: list[str] = []
    expected_type = expected_field.__class__.__name__
    actual_type = actual_field.__class__.__name__
    if expected_type != actual_type:
        issues.append(f"{field_label}: expected field type {expected_type}, found {actual_type}")
    for attr in ("null", "primary_key", "unique"):
        if getattr(expected_field, attr, None) != getattr(actual_field, attr, None):
            issues.append(
                f"{field_label}: expected {attr}={getattr(expected_field, attr, None)!r}, "
                f"found {getattr(actual_field, attr, None)!r}"
            )
    expected_max_length = getattr(expected_field, "max_length", None)
    actual_max_length = getattr(actual_field, "max_length", None)
    if expected_max_length != actual_max_length:
        issues.append(
            f"{field_label}: expected max_length={expected_max_length!r}, "
            f"found {actual_max_length!r}"
        )
    if _normalize_default(getattr(expected_field, "default", None)) != _normalize_default(
        getattr(actual_field, "default", None)
    ):
        issues.append(
            f"{field_label}: expected default="
            f"{_normalize_default(getattr(expected_field, 'default', None))!r}, "
            f"found {_normalize_default(getattr(actual_field, 'default', None))!r}"
        )
    expected_related = _normalize_related_model(getattr(expected_field.remote_field, "model", None))
    actual_related = _normalize_related_model(getattr(actual_field.remote_field, "model", None))
    if expected_related != actual_related:
        issues.append(
            f"{field_label}: expected related model {expected_related!r}, "
            f"found {actual_related!r}"
        )
    return issues


def collect_raw_sql_orm_mirror_contract_issues() -> list[str]:
    issues: list[str] = []
    models_by_label = django_models_by_label()
    migrations_by_id = _migration_class_by_id()

    for contract in iter_state_only_mirror_contracts():
        if not contract.creating_django_migration or not contract.orm_model:
            issues.append(f"{contract.table_name}: incomplete state-only mirror contract")
            continue
        migration_class = migrations_by_id.get(contract.creating_django_migration)
        model = models_by_label.get(contract.orm_model)
        if migration_class is None:
            issues.append(
                f"{contract.table_name}: missing migration {contract.creating_django_migration}"
            )
            continue
        if model is None:
            issues.append(f"{contract.table_name}: missing ORM model {contract.orm_model}")
            continue

        create_model_operation = None
        state_operations: list[Any] = []
        for operation in getattr(migration_class, "operations", []):
            if operation.__class__.__name__ != "SeparateDatabaseAndState":
                continue
            for state_operation in getattr(operation, "state_operations", []):
                state_operations.append(state_operation)
                if (
                    state_operation.__class__.__name__ == "CreateModel"
                    and str(state_operation.name) == model.__name__
                ):
                    create_model_operation = state_operation

        if create_model_operation is None:
            issues.append(
                f"{contract.table_name}: no CreateModel state operation found in "
                f"{contract.creating_django_migration}"
            )
            continue

        actual_fields = {
            field.name: field
            for field in model._meta.local_fields
            if not getattr(field, "auto_created", False) or field.primary_key
        }
        expected_fields = {
            str(field_name): field_object
            for field_name, field_object in create_model_operation.fields
        }
        if set(expected_fields) != set(actual_fields):
            missing = sorted(set(expected_fields) - set(actual_fields))
            extra = sorted(set(actual_fields) - set(expected_fields))
            if missing:
                issues.append(f"{contract.table_name}: model missing mirrored fields {missing}")
            if extra:
                issues.append(f"{contract.table_name}: model has extra mirrored fields {extra}")

        for field_name in sorted(set(expected_fields) & set(actual_fields)):
            issues.extend(
                _field_contract_issues(
                    expected_field=expected_fields[field_name],
                    actual_field=actual_fields[field_name],
                    field_label=f"{contract.table_name}.{field_name}",
                )
            )

        expected_indexes = {
            getattr(state_operation.index, "name", "")
            for state_operation in state_operations
            if state_operation.__class__.__name__ == "AddIndex"
            and str(getattr(state_operation, "model_name", "")).lower() == model.__name__.lower()
        }
        actual_indexes = {index.name for index in model._meta.indexes}
        if expected_indexes != actual_indexes:
            missing = sorted(expected_indexes - actual_indexes)
            extra = sorted(actual_indexes - expected_indexes)
            if missing:
                issues.append(f"{contract.table_name}: model missing mirrored indexes {missing}")
            if extra:
                issues.append(f"{contract.table_name}: model has extra indexes {extra}")

        expected_constraints = {
            getattr(state_operation.constraint, "name", "")
            for state_operation in state_operations
            if state_operation.__class__.__name__ == "AddConstraint"
            and str(getattr(state_operation, "model_name", "")).lower() == model.__name__.lower()
        }
        actual_constraints = {constraint.name for constraint in model._meta.constraints}
        if expected_constraints != actual_constraints:
            missing = sorted(expected_constraints - actual_constraints)
            extra = sorted(actual_constraints - expected_constraints)
            if missing:
                issues.append(
                    f"{contract.table_name}: model missing mirrored constraints {missing}"
                )
            if extra:
                issues.append(f"{contract.table_name}: model has extra constraints {extra}")

    return issues


def main() -> int:
    issues = collect_raw_sql_orm_mirror_contract_issues()
    if issues:
        print("verify_raw_sql_orm_mirror_contract: FAILED")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("verify_raw_sql_orm_mirror_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
