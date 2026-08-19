from __future__ import annotations

from scripts.verify_alembic_fresh_chain import REQUIRED_TABLES
from scripts.verify_no_blind_django_ddl_for_alembic_owned_tables import (
    collect_blind_ddl_issues_for_operations,
)
from scripts.verify_raw_sql_orm_mirror_contract import (
    collect_raw_sql_orm_mirror_contract_issues,
)
from scripts.verify_schema_authority_registry import collect_registry_issues
from scripts.verify_state_only_mirror_contract import collect_state_only_mirror_issues
from server.pg.schema_authority_registry import (
    get_schema_table_contract,
    iter_state_only_mirror_contracts,
)


def test_schema_authority_registry_covers_required_fresh_chain_tables() -> None:
    for table_name in REQUIRED_TABLES:
        contract = get_schema_table_contract(table_name)
        assert contract.owner == "alembic_physical"


def test_schema_authority_repo_contract_verifiers_pass() -> None:
    assert collect_registry_issues() == []
    assert collect_state_only_mirror_issues() == []
    assert collect_raw_sql_orm_mirror_contract_issues() == []


def test_state_only_mirror_contracts_cover_expected_import_tables() -> None:
    mirrored_tables = {contract.table_name for contract in iter_state_only_mirror_contracts()}
    assert {
        "imports_importworkflowstate",
        "imports_importagencyalias",
        "imports_importcorrectionsignal",
        "imports_importagencyprofile",
        "imports_importdeadletterrow",
    }.issubset(mirrored_tables)


def test_blind_ddl_helper_rejects_plain_create_model_for_alembic_owned_table() -> None:
    class CreateModel:
        def __init__(self, *, name: str) -> None:
            self.name = name

    issues = collect_blind_ddl_issues_for_operations(
        migration_id="imports.fake_9999",
        app_label="imports",
        operations=[CreateModel(name="ImportWorkflowState")],
    )

    assert issues == [
        "imports.fake_9999: CreateModel on Alembic-owned table "
        "imports_importworkflowstate must live in SeparateDatabaseAndState.state_operations only"
    ]
