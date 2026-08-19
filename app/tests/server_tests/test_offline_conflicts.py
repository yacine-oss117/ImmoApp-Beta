from __future__ import annotations

from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_conflicts import (
    add_conflict,
    list_conflicts,
    needs_review_count,
    remove_conflict,
)
from app.services.offline_types import OfflineConflict


def _scope(suffix: str = "conflicts") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_conflicts_round_trip_and_remove() -> None:
    scope = _scope()
    conflict = OfflineConflict(
        op_id="op-1",
        entity_type="client",
        local_id=-1,
        reason_code="sync_review_required",
        message="Needs review",
    )

    add_conflict(conflict, scope=scope)

    items = list_conflicts(scope=scope)
    assert len(items) == 1
    assert items[0].op_id == "op-1"
    assert needs_review_count(scope=scope) == 1

    remove_conflict("op-1", scope=scope)

    assert list_conflicts(scope=scope) == []
    assert needs_review_count(scope=scope) == 0
