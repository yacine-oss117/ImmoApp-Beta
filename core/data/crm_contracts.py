"""
Contract CRUD and lifecycle operations for CRM.
"""

from __future__ import annotations

from core.data.crm_contracts_cleanup import cleanup_orphan_contracts
from core.data.crm_contracts_read import (
    fetch_contracts,
    fetch_deleted_contracts,
    fetch_pending_contracts,
    get_contract_by_id,
)
from core.data.crm_contracts_status import (
    archive_demande_offer,
    update_client_status,
    update_listing_status,
)
from core.data.crm_contracts_write import (
    CONTRACT_STATUSES,
    activate_contract,
    cancel_contract,
    create_contract,
    delete_contract,
    print_contract,
    purge_contract,
    restore_contract,
    update_contract,
)

__all__ = [
    "CONTRACT_STATUSES",
    "create_contract",
    "fetch_contracts",
    "update_contract",
    "update_client_status",
    "update_listing_status",
    "archive_demande_offer",
    "delete_contract",
    "get_contract_by_id",
    "print_contract",
    "activate_contract",
    "cancel_contract",
    "cleanup_orphan_contracts",
    "fetch_pending_contracts",
    "fetch_deleted_contracts",
    "restore_contract",
    "purge_contract",
]
