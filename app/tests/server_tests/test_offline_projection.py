from __future__ import annotations

import app.services.offline_projection as projection
from app.models import Client
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_projection import (
    OfflineProjectionRecord,
    get_projection_record,
    overlay_model_detail,
    overlay_model_list,
    upsert_projection_record,
)


def _scope(suffix: str = "projection") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_overlay_model_list_prepends_local_only_records() -> None:
    scope = _scope()
    server_items = [Client.from_row({"id": 7, "family_name": "Server Client"})]
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="client",
            local_id=-1,
            server_id=None,
            data={"id": -1, "family_name": "Offline Client"},
            sync_status="pending",
            is_local_only=True,
        ),
        scope=scope,
    )

    merged = overlay_model_list("client", server_items, scope=scope)

    assert [int(item.id or 0) for item in merged] == [-1, 7]
    assert merged[0].is_local_only is True
    assert merged[0].sync_status == "pending"


def test_overlay_model_list_hides_pending_delete_records() -> None:
    scope = _scope("delete")
    server_items = [
        Client.from_row({"id": 7, "family_name": "Delete Me"}),
        Client.from_row({"id": 8, "family_name": "Keep Me"}),
    ]
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="client",
            local_id=7,
            server_id=7,
            data={"id": 7, "family_name": "Delete Me"},
            sync_status="pending_delete",
            is_local_only=False,
        ),
        scope=scope,
    )

    merged = overlay_model_list("client", server_items, scope=scope)

    assert [int(item.id or 0) for item in merged] == [8]


def test_overlay_model_detail_returns_temp_projection() -> None:
    scope = _scope("detail")
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="client",
            local_id=-2,
            server_id=None,
            data={"id": -2, "family_name": "Temp Client"},
            sync_status="pending",
            is_local_only=True,
        ),
        scope=scope,
    )

    item = overlay_model_detail("client", -2, None, scope=scope)

    assert item is not None
    assert int(item.id or 0) == -2
    assert item.family_name == "Temp Client"
    assert item.is_local_only is True
    assert get_projection_record("client", -2, scope=scope) is not None


def test_overlay_model_list_keeps_synced_positive_projection_until_server_includes_it() -> None:
    scope = _scope("reconciled")
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="client",
            local_id=41,
            server_id=41,
            data={"id": 41, "family_name": "Reconciled Client"},
            sync_status="synced",
            is_local_only=False,
        ),
        scope=scope,
    )

    merged = overlay_model_list("client", [], scope=scope)

    assert [int(item.id or 0) for item in merged] == [41]
    assert merged[0].family_name == "Reconciled Client"
    assert merged[0].sync_status == "synced"


def test_overlay_model_list_falls_back_to_server_items_without_scope(monkeypatch) -> None:
    server_items = [Client.from_row({"id": 7, "family_name": "Server Client"})]
    monkeypatch.setattr(projection, "get_active_account_scope", lambda: None)

    merged = overlay_model_list("client", server_items)

    assert [int(item.id or 0) for item in merged] == [7]
    assert merged[0].family_name == "Server Client"
