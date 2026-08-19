from __future__ import annotations

from server.services import media
from server.services.storage_config import StorageConfig


def test_load_agency_media_skips_large(monkeypatch) -> None:
    monkeypatch.setattr(media.agency_settings, "get_agency_setting", lambda *_args, **_kw: "s1")

    def fake_get_storage_object(_session, _storage_id):
        return {
            "id": "s1",
            "status": "ready",
            "size_bytes": 999,
            "object_key": "logos/logo.png",
        }

    monkeypatch.setattr(media.storage_data, "get_storage_object", fake_get_storage_object)

    fake_config = StorageConfig(
        endpoint_url=None,
        access_key="",
        secret_key="",
        bucket="immoapp",
        region=None,
        use_ssl=False,
        max_file_bytes=10_000,
        max_import_bytes=10_000,
        max_offer_photo_bytes=10_000,
        max_agency_media_bytes=10_000,
        max_inline_media_bytes=1,
        agency_quota_bytes=None,
        user_daily_max_files=None,
        virus_scan=False,
        virus_scan_required=False,
        presign_default_seconds=900,
        clamd_socket=None,
        clamd_host=None,
        clamd_port=3310,
        clamd_timeout=10.0,
        sse=None,
        sse_kms_key_id=None,
    )
    monkeypatch.setattr(media, "get_storage_config", lambda: fake_config)

    def _explode(*_args, **_kwargs):
        raise AssertionError("fetch_small_bytes should not be called for oversized media")

    monkeypatch.setattr(media, "fetch_small_bytes", _explode)

    assert media.load_agency_media("logo") is None
