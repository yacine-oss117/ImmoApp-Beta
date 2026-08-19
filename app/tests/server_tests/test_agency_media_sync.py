from __future__ import annotations

from pathlib import Path

import pytest

import app.services.agency_media as agency_media
import app.services.upload_queue as upload_queue
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_conflicts import list_conflicts


def _scope(suffix: str = "media") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_enqueue_media_requires_active_account_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    import importlib

    mod = importlib.reload(upload_queue)
    source = tmp_path / "logo.png"
    source.write_bytes(b"png")

    monkeypatch.setattr(
        mod,
        "require_active_account_scope",
        lambda: (_ for _ in ()).throw(RuntimeError("missing scope")),
    )

    with pytest.raises(RuntimeError, match="missing scope"):
        mod.enqueue_media("logo", str(source))


def test_flush_pending_media_uploads_respects_batch_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    scope = _scope("limit")
    source = tmp_path / "logo.png"
    source.write_bytes(b"png")

    import importlib

    queue_mod = importlib.reload(upload_queue)
    media_mod = importlib.reload(agency_media)
    monkeypatch.setattr(media_mod, "get_offline_mode", lambda: False)
    monkeypatch.setattr(
        media_mod, "_upload_media", lambda kind, path: f"stored:{kind}:{Path(path).name}"
    )

    for _ in range(3):
        queue_mod.enqueue_media("logo", str(source), scope=scope)

    flushed = media_mod.flush_pending_media_uploads(scope=scope, limit=2)

    assert flushed == 2
    assert queue_mod.pending_media_upload_count(scope=scope) == 1


def test_store_local_media_is_account_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    import importlib

    media_mod = importlib.reload(agency_media)
    scope_a = _scope("media-a")
    scope_b = _scope("media-b")
    source = tmp_path / "logo.png"
    source.write_bytes(b"png")

    monkeypatch.setattr(media_mod, "get_active_account_scope", lambda: scope_a)
    path_a = media_mod._store_local_media("logo", str(source))
    monkeypatch.setattr(media_mod, "get_active_account_scope", lambda: scope_b)
    path_b = media_mod._store_local_media("logo", str(source))

    assert path_a != path_b
    assert scope_a.account_dir in path_a
    assert scope_b.account_dir in path_b


def test_flush_pending_media_uploads_processes_offer_photos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    scope = _scope("offer-photo")
    source = tmp_path / "offer.jpg"
    source.write_bytes(b"jpg")

    import importlib

    queue_mod = importlib.reload(upload_queue)
    media_mod = importlib.reload(agency_media)
    monkeypatch.setattr(media_mod, "get_offline_mode", lambda: False)
    monkeypatch.setattr(
        media_mod,
        "process_pending_offer_photo_upload",
        lambda item, *, scope=None: 91,
    )

    queue_id = queue_mod.enqueue_offer_photo_upload(44, str(source), scope=scope)

    flushed = media_mod.flush_pending_media_uploads(scope=scope)

    assert flushed == 1
    assert queue_mod.get_media_upload(queue_id, scope=scope) is None


def test_flush_pending_media_uploads_marks_missing_offer_photo_for_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    scope = _scope("offer-photo-missing")
    source = tmp_path / "offer.jpg"
    source.write_bytes(b"jpg")

    import importlib

    queue_mod = importlib.reload(upload_queue)
    media_mod = importlib.reload(agency_media)
    monkeypatch.setattr(media_mod, "get_offline_mode", lambda: False)

    queue_id = queue_mod.enqueue_offer_photo_upload(44, str(source), scope=scope)
    queued = queue_mod.get_media_upload(queue_id, scope=scope)
    assert queued is not None
    Path(str(queued["path"])).unlink()

    flushed = media_mod.flush_pending_media_uploads(scope=scope)
    item = queue_mod.get_media_upload(queue_id, scope=scope)
    conflicts = list_conflicts(scope=scope)

    assert flushed == 0
    assert item is not None
    assert item["status"] == "needs_review"
    assert any(conflict.op_id == f"media:{queue_id}" for conflict in conflicts)
