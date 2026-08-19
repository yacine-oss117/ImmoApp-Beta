from __future__ import annotations

from pathlib import Path


def test_client_repository_uses_cursor_anchor_path() -> None:
    text = Path("app/services/client_repository.py").read_text(encoding="utf-8")
    assert "_CLIENT_CURSOR_ANCHORS" in text
    assert '"cursor"' in text
    assert "_fetch_clients_cursor_page(" in text


def test_listing_repository_uses_cursor_anchor_path() -> None:
    text = Path("app/services/listing_repository.py").read_text(encoding="utf-8")
    assert "_LISTING_CURSOR_ANCHORS" in text
    assert '"cursor"' in text
    assert "_fetch_listings_cursor_page(" in text
