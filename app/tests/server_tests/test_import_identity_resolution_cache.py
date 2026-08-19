from __future__ import annotations

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.services.duplicate_checker import DbDuplicateCandidate  # noqa: E402
from server.services.import_identity_resolution import IdentityResolutionCache  # noqa: E402


def _duplicate_candidate(existing_id: int) -> DbDuplicateCandidate:
    return DbDuplicateCandidate(
        existing_id=existing_id,
        row_version=1,
        family_name=f"Candidate {existing_id}",
        phone=f"0555001{existing_id:03d}",
        status="active",
        remarks=f"candidate-{existing_id}",
        match_confidence=0.9,
        match_reasons=["same phone"],
    )


def test_identity_resolution_cache_evicts_least_recent_root_phone_entry() -> None:
    cache = IdentityResolutionCache(max_entries=2)
    first_key = ("client", 7, "0555001001")
    second_key = ("client", 7, "0555001002")
    third_key = ("client", 7, "0555001003")

    cache.set_root_phone_candidates(first_key, [_duplicate_candidate(1)])
    cache.set_root_phone_candidates(second_key, [_duplicate_candidate(2)])

    recalled = cache.get_root_phone_candidates(first_key)
    assert recalled is not None
    recalled[0].match_reasons.append("mutated outside cache")

    cache.set_root_phone_candidates(third_key, [_duplicate_candidate(3)])

    assert cache.has_root_phone_candidates(first_key) is True
    assert cache.has_root_phone_candidates(second_key) is False
    assert cache.has_root_phone_candidates(third_key) is True
    cached_again = cache.get_root_phone_candidates(first_key)
    assert cached_again is not None
    assert cached_again[0].match_reasons == ["same phone"]


def test_identity_resolution_cache_bounds_child_candidate_entries() -> None:
    cache = IdentityResolutionCache(max_entries=2)
    first_key = ("demande", 7, 11)
    second_key = ("demande", 7, 12)
    third_key = ("demande", 7, 13)

    cache.set_child_candidates(first_key, [{"id": 111, "remarks": "first"}])
    cache.set_child_candidates(second_key, [{"id": 112, "remarks": "second"}])
    assert cache.get_child_candidates(first_key) == [{"id": 111, "remarks": "first"}]

    cache.set_child_candidates(third_key, [{"id": 113, "remarks": "third"}])

    assert cache.has_child_candidates(first_key) is True
    assert cache.has_child_candidates(second_key) is False
    assert cache.has_child_candidates(third_key) is True


def test_identity_resolution_cache_bounds_child_anchor_entries() -> None:
    cache = IdentityResolutionCache(max_entries=2)
    first_key = ("client_side", 7, ("phone:0555001001",))
    second_key = ("client_side", 7, ("phone:0555001002",))
    third_key = ("client_side", 7, ("phone:0555001003",))

    cache.set_child_anchor_id(first_key, 101)
    cache.set_child_anchor_id(second_key, 102)
    assert cache.get_child_anchor_id(first_key) == 101

    cache.set_child_anchor_id(third_key, 103)

    assert cache.get_child_anchor_id(first_key) == 101
    assert cache.get_child_anchor_id(second_key) is None
    assert cache.get_child_anchor_id(third_key) == 103
