from __future__ import annotations

import pytest

from server.services.import_identity_resolution import (
    IdentityResolutionCache,
    ResolutionResult,
    prefetch_child_match_cache,
    prefetch_root_match_cache,
    resolve_child_anchor,
    resolve_child_matches,
    resolve_root_matches,
)


class _UnexpectedSessionUse:
    def execute(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - safety net
        raise AssertionError("session.execute should not be used in this test")


def test_resolve_child_anchor_uses_prefixed_phone_key_from_local_anchor_map() -> None:
    anchor_id = resolve_child_anchor(
        topology_side="client_side",
        row_data={"phone": "0555 12 34 56"},
        session=_UnexpectedSessionUse(),
        agency_id=7,
        local_anchor_map={"phone:0555123456": 321},
    )

    assert anchor_id == 321


def test_resolve_child_anchor_uses_prefixed_name_key_from_local_anchor_map() -> None:
    anchor_id = resolve_child_anchor(
        topology_side="listing_side",
        row_data={"family_name": "Villa Hydra"},
        session=_UnexpectedSessionUse(),
        agency_id=7,
        local_anchor_map={"name:villa hydra": 654},
    )

    assert anchor_id == 654


def test_resolve_child_anchor_returns_ambiguous_sentinel_for_client_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def _fake_resolve_root_matches(**_kwargs: object) -> ResolutionResult:
        calls["count"] += 1
        return ResolutionResult(
            candidate_matches=[{"id": 91, "match_confidence": 0.77}],
            suggested_action="review_ambiguous",
        )

    monkeypatch.setattr(
        "server.services.import_identity_resolution.resolve_root_matches",
        _fake_resolve_root_matches,
    )

    cache = IdentityResolutionCache()
    first = resolve_child_anchor(
        topology_side="client_side",
        row_data={"phone": "0555 12 34 56", "family_name": "Anchor Client"},
        session=object(),
        agency_id=7,
        cache=cache,
    )
    second = resolve_child_anchor(
        topology_side="client_side",
        row_data={"phone": "0555 12 34 56", "family_name": "Anchor Client"},
        session=object(),
        agency_id=7,
        cache=cache,
    )

    assert first == -1
    assert second == -1
    assert calls["count"] == 1


def test_resolve_child_anchor_returns_ambiguous_sentinel_for_listing_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_resolve_root_matches(**_kwargs: object) -> ResolutionResult:
        return ResolutionResult(
            candidate_matches=[{"id": 42, "match_confidence": 0.69}],
            suggested_action="review_ambiguous",
        )

    monkeypatch.setattr(
        "server.services.import_identity_resolution.resolve_root_matches",
        _fake_resolve_root_matches,
    )

    anchor_id = resolve_child_anchor(
        topology_side="listing_side",
        row_data={"family_name": "Villa Hydra", "phone": "0666 11 22 33"},
        session=object(),
        agency_id=7,
        cache=IdentityResolutionCache(),
    )

    assert anchor_id == -1


def test_resolve_child_matches_returns_update_for_strong_demande_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.services.import_identity_resolution._query_child_candidates",
        lambda **_kwargs: [
            {
                "id": 11,
                "row_version": 4,
                "client_id": 98,
                "type": "apartment",
                "type_id": 3,
                "action": "buy",
                "action_id": 1,
                "wilaya": "alger",
                "wilaya_id": 16,
                "locations": "hydra",
                "beds_min": 3,
                "surface_min": 90,
                "surface_max": 120,
                "budget_min": 5000000,
                "budget_max": 6500000,
                "remarks": "",
            }
        ],
    )

    result = resolve_child_matches(
        entity_type="demande",
        row_data={
            "client_id": 98,
            "type": "apartment",
            "type_id": 3,
            "action": "buy",
            "action_id": 1,
            "wilaya": "alger",
            "wilaya_id": 16,
            "locations": "hydra",
            "beds_min": 3,
            "surface_min": 95,
            "surface_max": 115,
            "budget_min": 5100000,
            "budget_max": 6400000,
        },
        session=object(),
        agency_id=7,
        anchor_id=98,
    )

    assert result.suggested_action == "update_existing"
    assert result.suggested_existing_id == 11
    assert result.suggested_confidence >= 0.93


def test_resolve_child_matches_returns_review_for_mid_confidence_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.services.import_identity_resolution._query_child_candidates",
        lambda **_kwargs: [
            {
                "id": 22,
                "row_version": 2,
                "listing_id": 77,
                "type": "villa",
                "type_id": 5,
                "action": "sell",
                "action_id": 2,
                "wilaya": "oran",
                "wilaya_id": 31,
                "location": "akid lotfi",
                "beds": 4,
                "surface": 180,
                "budget": 24000000,
                "status": "available",
                "remarks": "",
            }
        ],
    )

    result = resolve_child_matches(
        entity_type="offer",
        row_data={
            "listing_id": 77,
            "type": "villa",
            "type_id": 5,
            "action": "sell",
            "action_id": 2,
            "wilaya": "oran",
            "wilaya_id": 31,
            "location": "akid lotfi extension",
            "beds": 5,
            "surface": 205,
            "budget": 28000000,
            "status": "available",
        },
        session=object(),
        agency_id=7,
        anchor_id=77,
    )

    assert result.suggested_action == "review_ambiguous"
    assert result.suggested_existing_id == 22
    assert 0.65 <= result.suggested_confidence < 0.93


def test_resolve_root_matches_reuses_cached_phone_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, int] = {"count": 0}

    def _fake_lookup(
        self: object,
        phones: list[str],
        entity_type: str,
        session: object,
        *,
        agency_id: int | None = None,
    ) -> dict[str, list[object]]:
        del self, entity_type, session, agency_id
        calls["count"] += 1
        return {
            phones[0]: [
                type(
                    "Candidate",
                    (),
                    {
                        "existing_id": 91,
                        "row_version": 3,
                        "family_name": "Hasna Amrani",
                        "phone": phones[0],
                        "remarks": "",
                        "status": "active",
                    },
                )()
            ]
        }

    monkeypatch.setattr(
        "server.services.duplicate_checker.DatabaseDuplicateChecker._lookup_phones",
        _fake_lookup,
    )

    cache = IdentityResolutionCache()
    for remarks in ("a", "b"):
        result = resolve_root_matches(
            entity_type="client",
            row_data={"phone": "0555 12 34 56", "family_name": "Hasna Amrani", "remarks": remarks},
            session=object(),
            agency_id=7,
            cache=cache,
        )
        assert result.suggested_existing_id == 91

    assert calls["count"] == 1


def test_prefetch_root_match_cache_batches_phone_lookups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_calls: list[list[str]] = []

    def _fake_lookup(
        self: object,
        phones: list[str],
        entity_type: str,
        session: object,
        *,
        agency_id: int | None = None,
    ) -> dict[str, list[object]]:
        del self, entity_type, session, agency_id
        seen_calls.append(list(phones))
        return {
            phone: [
                type(
                    "Candidate",
                    (),
                    {
                        "existing_id": index + 1,
                        "row_version": 2,
                        "family_name": f"Client {index + 1}",
                        "phone": phone,
                        "remarks": "",
                        "status": "active",
                    },
                )()
            ]
            for index, phone in enumerate(phones)
        }

    monkeypatch.setattr(
        "server.services.duplicate_checker.DatabaseDuplicateChecker._lookup_phones",
        _fake_lookup,
    )

    cache = IdentityResolutionCache()
    rows = [
        {"phone": "0555 12 34 56", "family_name": "Client One"},
        {"phone": "0666 11 22 33", "family_name": "Client Two"},
        {"phone": "0555 12 34 56", "family_name": "Client One Duplicate"},
    ]
    prefetch_root_match_cache(
        entity_type="client",
        rows=rows,
        session=object(),
        agency_id=7,
        cache=cache,
    )

    assert seen_calls == [["0555123456", "0666112233"]]
    for row in rows[:2]:
        result = resolve_root_matches(
            entity_type="client",
            row_data=row,
            session=object(),
            agency_id=7,
            cache=cache,
        )
        assert result.suggested_existing_id > 0
    assert len(seen_calls) == 1


def test_resolve_child_matches_reuses_cached_anchor_candidates() -> None:
    class _CountingSession:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, *_args: object, **_kwargs: object) -> "_CountingSession":
            self.calls += 1
            return self

        def fetchall(self) -> list[dict[str, object]]:
            return [
                {
                    "id": 11,
                    "row_version": 4,
                    "client_id": 98,
                    "type": "apartment",
                    "type_id": 3,
                    "action": "buy",
                    "action_id": 1,
                    "wilaya": "alger",
                    "wilaya_id": 16,
                    "locations": "hydra",
                    "beds_min": 3,
                    "surface_min": 90,
                    "surface_max": 120,
                    "budget_min": 5000000,
                    "budget_max": 6500000,
                    "remarks": "",
                }
            ]

    session = _CountingSession()
    cache = IdentityResolutionCache()

    first = resolve_child_matches(
        entity_type="demande",
        row_data={
            "client_id": 98,
            "type": "apartment",
            "type_id": 3,
            "action": "buy",
            "action_id": 1,
            "wilaya": "alger",
            "wilaya_id": 16,
            "locations": "hydra",
            "beds_min": 3,
            "surface_min": 95,
            "surface_max": 115,
            "budget_min": 5100000,
            "budget_max": 6400000,
        },
        session=session,
        agency_id=7,
        anchor_id=98,
        cache=cache,
    )
    second = resolve_child_matches(
        entity_type="demande",
        row_data={
            "client_id": 98,
            "type": "apartment",
            "type_id": 3,
            "action": "buy",
            "action_id": 1,
            "wilaya": "alger",
            "wilaya_id": 16,
            "locations": "hydra centre",
            "beds_min": 3,
            "surface_min": 96,
            "surface_max": 116,
            "budget_min": 5200000,
            "budget_max": 6450000,
        },
        session=session,
        agency_id=7,
        anchor_id=98,
        cache=cache,
    )

    assert first.suggested_existing_id == 11
    assert second.suggested_existing_id == 11
    assert session.calls == 1


def test_prefetch_child_match_cache_batches_anchor_queries() -> None:
    class _CountingSession:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, *_args: object, **_kwargs: object) -> "_CountingSession":
            self.calls += 1
            return self

        def fetchall(self) -> list[dict[str, object]]:
            return [
                {
                    "id": 11,
                    "row_version": 4,
                    "client_id": 98,
                    "type": "apartment",
                    "type_id": 3,
                    "action": "buy",
                    "action_id": 1,
                    "wilaya": "alger",
                    "wilaya_id": 16,
                    "locations": "hydra",
                    "beds_min": 3,
                    "surface_min": 90,
                    "surface_max": 120,
                    "budget_min": 5000000,
                    "budget_max": 6500000,
                    "remarks": "",
                },
                {
                    "id": 12,
                    "row_version": 2,
                    "client_id": 99,
                    "type": "apartment",
                    "type_id": 3,
                    "action": "buy",
                    "action_id": 1,
                    "wilaya": "alger",
                    "wilaya_id": 16,
                    "locations": "kouba",
                    "beds_min": 2,
                    "surface_min": 70,
                    "surface_max": 90,
                    "budget_min": 3000000,
                    "budget_max": 4200000,
                    "remarks": "",
                },
            ]

    session = _CountingSession()
    cache = IdentityResolutionCache()
    prefetch_child_match_cache(
        entity_type="demande",
        anchor_ids={98, 99},
        session=session,
        agency_id=7,
        cache=cache,
    )

    first = resolve_child_matches(
        entity_type="demande",
        row_data={
            "client_id": 98,
            "type": "apartment",
            "type_id": 3,
            "action": "buy",
            "action_id": 1,
            "wilaya": "alger",
            "wilaya_id": 16,
            "locations": "hydra centre",
            "beds_min": 3,
            "surface_min": 95,
            "surface_max": 115,
            "budget_min": 5100000,
            "budget_max": 6400000,
        },
        session=session,
        agency_id=7,
        anchor_id=98,
        cache=cache,
    )
    second = resolve_child_matches(
        entity_type="demande",
        row_data={
            "client_id": 99,
            "type": "apartment",
            "type_id": 3,
            "action": "buy",
            "action_id": 1,
            "wilaya": "alger",
            "wilaya_id": 16,
            "locations": "kouba",
            "beds_min": 2,
            "surface_min": 72,
            "surface_max": 88,
            "budget_min": 3100000,
            "budget_max": 4100000,
        },
        session=session,
        agency_id=7,
        anchor_id=99,
        cache=cache,
    )

    assert first.suggested_existing_id == 11
    assert second.suggested_existing_id == 12
    assert session.calls == 1
