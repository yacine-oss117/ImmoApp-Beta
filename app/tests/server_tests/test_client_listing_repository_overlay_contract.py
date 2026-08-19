from __future__ import annotations

from types import SimpleNamespace

from app.services import client_repository, listing_repository


def test_client_repository_cursor_path_applies_overlay_model_list(
    monkeypatch,
) -> None:
    client_repository.reset_client_cursor_anchors()
    merged = [SimpleNamespace(id=999)]
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        client_repository,
        "_fetch_clients_cursor_page",
        lambda **_kwargs: ([SimpleNamespace(id=1)], None),
    )
    monkeypatch.setattr(
        client_repository,
        "overlay_model_list",
        lambda entity_type, items: calls.setdefault(
            "payload",
            (entity_type, [getattr(item, "id", 0) for item in items]),
        )
        and merged,
    )

    result = client_repository.fetch_clients(limit=25, offset=0)

    assert calls["payload"] == ("client", [1])
    assert result == merged


def test_listing_repository_cursor_path_applies_overlay_model_list(
    monkeypatch,
) -> None:
    listing_repository.reset_listing_cursor_anchors()
    merged = [SimpleNamespace(id=888)]
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        listing_repository,
        "_fetch_listings_cursor_page",
        lambda **_kwargs: ([SimpleNamespace(id=2)], None),
    )
    monkeypatch.setattr(
        listing_repository,
        "overlay_model_list",
        lambda entity_type, items: calls.setdefault(
            "payload",
            (entity_type, [getattr(item, "id", 0) for item in items]),
        )
        and merged,
    )

    result = listing_repository.fetch_listings(limit=25, offset=0)

    assert calls["payload"] == ("listing", [2])
    assert result == merged
