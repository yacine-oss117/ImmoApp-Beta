"""
CRM Service Orchestrator - facade for contracts, visits, and articles.
"""

from app.services.crm_articles import (
    copy_standard_clauses,
    create_article,
    delete_article,
    get_articles_for_contract,
    renumber_articles,
    update_article,
)
from app.services.crm_contracts import (
    activate_contract,
    cancel_contract,
    create_contract,
    delete_contract,
    fetch_contracts,
    fetch_deleted_contracts,
    print_contract,
    purge_contract,
    restore_contract,
    update_contract,
)
from app.services.crm_visits import (
    create_visit,
    delete_visit,
    fetch_deleted_visits,
    fetch_visits,
    purge_visit,
    restore_visit,
    update_visit,
)

__all__ = [
    "create_contract",
    "create_visit",
    "delete_contract",
    "delete_visit",
    "fetch_contracts",
    "fetch_visits",
    "print_contract",
    "activate_contract",
    "cancel_contract",
    "update_visit",
    "fetch_deleted_contracts",
    "restore_contract",
    "purge_contract",
    "update_contract",
    "fetch_deleted_visits",
    "restore_visit",
    "purge_visit",
    "create_article",
    "update_article",
    "delete_article",
    "get_articles_for_contract",
    "renumber_articles",
    "copy_standard_clauses",
]
