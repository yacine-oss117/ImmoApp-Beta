from __future__ import annotations

import pytest

from app.services import listing_repository, offer_repository
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


def test_offline_offer_create_blocks_on_temp_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.offline_entity_mutations as mutations

    scope = _scope("offer-create")
    monkeypatch.setenv("IMMOAPP_OFFLINE_CREATES_ENABLED", "1")
    monkeypatch.setattr(mutations, "require_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        mutations.api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    listing_id = listing_repository.upsert_listing({"title": "Offline Listing"})
    offer_id = offer_repository.create_offer(listing_id, {"price": 10})

    assert listing_id < 0
    assert offer_id < 0
    ops = list_operations(scope=scope)
    status_by_type = {(op.entity_type, op.local_id): op.status for op in ops}
    assert status_by_type[("listing", listing_id)] == "pending"
    assert status_by_type[("offer", offer_id)] == "blocked"
