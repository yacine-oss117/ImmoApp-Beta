"""
Postgres-backed CRM operations with validation (facade).
"""

from __future__ import annotations

from .crm_articles import (
    copy_standard_clauses,
    create_article,
    delete_article,
    get_articles_for_contract,
    renumber_articles,
    update_article,
)
from .crm_contracts import (
    activate_contract,
    cancel_contract,
    create_contract,
    delete_contract,
    fetch_contracts,
    fetch_deleted_contracts,
    get_contract_by_id,
    get_total_contract_count,
    get_total_deleted_contract_count,
    print_contract,
    purge_contract,
    restore_contract,
    update_contract,
)
from .crm_visits import (
    create_visit,
    delete_visit,
    fetch_deleted_visits,
    fetch_visits,
    get_total_deleted_visit_count,
    get_total_visit_count,
    get_visit_by_id,
    purge_visit,
    restore_visit,
    update_visit,
)

__all__ = [
    "create_contract",
    "update_contract",
    "fetch_contracts",
    "fetch_deleted_contracts",
    "get_total_contract_count",
    "get_total_deleted_contract_count",
    "delete_contract",
    "restore_contract",
    "purge_contract",
    "print_contract",
    "activate_contract",
    "cancel_contract",
    "get_contract_by_id",
    "create_visit",
    "fetch_visits",
    "update_visit",
    "delete_visit",
    "get_visit_by_id",
    "fetch_deleted_visits",
    "get_total_visit_count",
    "get_total_deleted_visit_count",
    "restore_visit",
    "purge_visit",
    "create_article",
    "update_article",
    "delete_article",
    "get_articles_for_contract",
    "renumber_articles",
    "copy_standard_clauses",
]
