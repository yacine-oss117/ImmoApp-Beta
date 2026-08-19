from __future__ import annotations

from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_ids import allocate_temp_id, record_reconciled_id, resolve_reconciled_id


def _scope(suffix: str = "ids") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_allocate_temp_ids_are_negative_and_per_entity() -> None:
    scope = _scope()

    assert allocate_temp_id("client", scope=scope) == -1
    assert allocate_temp_id("client", scope=scope) == -2
    assert allocate_temp_id("demande", scope=scope) == -1
    assert allocate_temp_id("demande", scope=scope) == -2


def test_reconciled_id_round_trip() -> None:
    scope = _scope("map")

    assert resolve_reconciled_id("client", -1, scope=scope) is None

    record_reconciled_id("client", -1, 42, scope=scope)

    assert resolve_reconciled_id("client", -1, scope=scope) == 42
    assert resolve_reconciled_id("client", 42, scope=scope) == 42
