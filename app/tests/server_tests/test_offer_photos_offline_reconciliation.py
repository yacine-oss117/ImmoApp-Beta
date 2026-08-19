from __future__ import annotations

from pathlib import Path

import pytest

import app.services.api_client as api_module
from app.services import offline_reconciler as reconciler
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_op_log import queue_create_operation
from app.services.offline_projection import OfflineProjectionRecord, upsert_projection_record
from app.services.upload_queue import enqueue_offer_photo_upload, get_media_upload


def _scope(suffix: str = "offer-photo-reconcile") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_offer_photo_queue_unblocks_when_temp_offer_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    scope = _scope("reconcile")
    source = tmp_path / "offer.jpg"
    source.write_bytes(b"jpg")

    queue_create_operation(
        "offer",
        -1,
        payload={
            "method": "POST",
            "path": "/offers",
            "body": {"remarks": "Offline offer"},
            "headers": {"Idempotency-Key": "offline:test:offer"},
        },
        dedupe_key="offline:test:offer",
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="offer",
            local_id=-1,
            server_id=None,
            data={"id": -1, "listing_id": 7, "remarks": "Offline offer"},
            sync_status="pending",
            is_local_only=True,
        ),
        scope=scope,
    )

    queue_id = enqueue_offer_photo_upload(-1, str(source), scope=scope)
    queued = get_media_upload(queue_id, scope=scope)

    assert queued is not None
    assert queued["status"] == "blocked"
    assert int(queued["parent_local_id"]) == -1

    monkeypatch.setattr(
        api_module,
        "_send_request",
        lambda method, path, **kwargs: {"id": 81, "item": {"id": 81, "listing_id": 7}},
    )

    result = reconciler.replay_offline_operations(scope=scope)
    updated = get_media_upload(queue_id, scope=scope)

    assert result["flushed"] == 1
    assert updated is not None
    assert updated["status"] == "pending"
    assert int(updated["parent_local_id"]) == 81
