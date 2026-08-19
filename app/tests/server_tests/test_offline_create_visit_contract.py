from __future__ import annotations

import pytest

from app.services import client_repository, crm_contracts, crm_visits, listing_repository
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_op_log import list_operations


def _scope(suffix: str = "scope") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_offline_visit_and_contract_block_until_both_parents_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.offline_entity_mutations as mutations

    scope = _scope("visit-contract")
    monkeypatch.setenv("IMMOAPP_OFFLINE_CREATES_ENABLED", "1")
    monkeypatch.setattr(mutations, "require_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        mutations.api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    client_id = client_repository.upsert_client({"full_name": "Offline Client"})
    listing_id = listing_repository.upsert_listing({"title": "Offline Listing"})
    visit_id = crm_visits.create_visit({"client_id": client_id, "listing_id": listing_id})
    contract_id = crm_contracts.create_contract(
        {
            "client_id": client_id,
            "listing_id": listing_id,
            "contract_type": "sale",
        }
    )

    assert client_id < 0 and listing_id < 0
    assert visit_id < 0 and contract_id < 0
    ops = list_operations(scope=scope)
    status_by_type = {(op.entity_type, op.local_id): op.status for op in ops}
    assert status_by_type[("visit", visit_id)] == "blocked"
    assert status_by_type[("contract", contract_id)] == "blocked"
