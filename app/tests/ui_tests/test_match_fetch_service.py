from __future__ import annotations

from app.services import match_fetch


def test_get_matches_for_client_unwraps_item_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        match_fetch,
        "api_get",
        lambda _path, params=None: {
            "item": {
                "client_id": 42,
                "total_unique_offers": 3,
                "demande_results": [
                    {
                        "demande_id": 7,
                        "demande_summary": "Hydra",
                        "matches": [],
                        "total_count": 0,
                    }
                ],
            }
        },
    )

    result = match_fetch.get_matches_for_client(42, limit_per_demande=20, score_threshold=0.0)

    assert result.client_id == 42
    assert result.total_unique_offers == 3
    assert len(result.demande_results) == 1
    assert result.demande_results[0].demande_id == 7


def test_get_matches_for_client_keeps_flat_payload_compatibility(monkeypatch) -> None:
    monkeypatch.setattr(
        match_fetch,
        "api_get",
        lambda _path, params=None: {
            "client_id": 99,
            "total_unique_offers": 1,
            "demande_results": [],
        },
    )

    result = match_fetch.get_matches_for_client(99)

    assert result.client_id == 99
    assert result.total_unique_offers == 1
