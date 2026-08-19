from __future__ import annotations

import app.services.demande_repository as demande_repository
import app.services.offer_repository as offer_repository
from app.models import Offer
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_projection import (
    OfflineProjectionRecord,
    list_projection_records,
    overlay_model_detail,
    upsert_projection_record,
)


def _scope(suffix: str) -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_overlay_client_demandes_keeps_reconciled_positive_projection(
    monkeypatch,
) -> None:
    scope = _scope("client-demandes")
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="demande",
            local_id=88,
            server_id=88,
            data={"id": 88, "client_id": 77, "budget_min": 10},
            sync_status="synced",
            is_local_only=False,
        ),
        scope=scope,
    )
    monkeypatch.setattr(
        demande_repository,
        "list_projection_records",
        lambda entity_type: list_projection_records(entity_type, scope=scope),
    )
    monkeypatch.setattr(
        demande_repository,
        "overlay_model_detail",
        lambda entity_type, local_id, item: overlay_model_detail(
            entity_type, local_id, item, scope=scope
        ),
    )

    merged = demande_repository._overlay_client_demandes(77, [])

    assert [int(item.id or 0) for item in merged] == [88]


def test_overlay_listing_offers_keeps_reconciled_positive_projection(monkeypatch) -> None:
    scope = _scope("listing-offers")
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="offer",
            local_id=91,
            server_id=91,
            data={"id": 91, "listing_id": 55, "price": 10},
            sync_status="synced",
            is_local_only=False,
        ),
        scope=scope,
    )
    monkeypatch.setattr(
        offer_repository,
        "list_projection_records",
        lambda entity_type: list_projection_records(entity_type, scope=scope),
    )
    monkeypatch.setattr(
        offer_repository,
        "overlay_model_detail",
        lambda entity_type, local_id, item: overlay_model_detail(
            entity_type, local_id, item, scope=scope
        ),
    )

    merged = offer_repository._overlay_listing_offers(55, [])

    assert [int(item.id or 0) for item in merged if isinstance(item, Offer)] == [91]
