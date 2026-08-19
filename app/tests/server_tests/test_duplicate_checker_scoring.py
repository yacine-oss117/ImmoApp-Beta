from __future__ import annotations

import pytest

from core.importer.security import import_security_limits
from server.services.duplicate_checker import (
    DbDuplicateCandidate,
    _score_candidates_for_row,
)


def test_duplicate_checker_scores_exact_name_match_as_confident_update() -> None:
    candidates = [
        DbDuplicateCandidate(
            existing_id=12,
            row_version=4,
            family_name="Hasna Amrani",
            phone="0555123456",
            status="active",
        )
    ]

    scored, suggested_action, suggested_existing_id = _score_candidates_for_row(
        {"family_name": "Hasna Amrani", "phone": "+213555123456"},
        candidates,
    )

    assert suggested_action == "update_existing"
    assert suggested_existing_id == 12
    assert len(scored) == 1
    assert scored[0].match_confidence >= 0.9
    assert "same phone" in scored[0].match_reasons
    assert "same name" in scored[0].match_reasons


def test_duplicate_checker_keeps_phone_only_match_in_review() -> None:
    candidates = [
        DbDuplicateCandidate(
            existing_id=12,
            row_version=4,
            family_name="Agency Existing",
            phone="0555123456",
            status="active",
        )
    ]

    scored, suggested_action, suggested_existing_id = _score_candidates_for_row(
        {"family_name": "Different Imported Name", "phone": "+213555123456"},
        candidates,
    )

    assert suggested_action == "review_ambiguous"
    assert suggested_existing_id == 12
    assert len(scored) == 1
    assert 0.7 <= scored[0].match_confidence < 0.9
    assert scored[0].match_reasons[0] == "same phone"


def test_duplicate_checker_prefers_better_name_match_when_multiple_candidates_exist() -> None:
    candidates = [
        DbDuplicateCandidate(
            existing_id=24,
            row_version=3,
            family_name="Agency Existing",
            phone="0555123456",
            status="active",
        ),
        DbDuplicateCandidate(
            existing_id=18,
            row_version=5,
            family_name="Hasna Amrani",
            phone="0555123456",
            status="active",
        ),
    ]

    scored, suggested_action, suggested_existing_id = _score_candidates_for_row(
        {"family_name": "Hasna Amrani", "phone": "0555123456"},
        candidates,
    )

    assert [candidate.existing_id for candidate in scored] == [18, 24]
    assert suggested_action == "update_existing"
    assert suggested_existing_id == 18


def test_duplicate_checker_caps_candidate_list_for_review_payloads() -> None:
    candidates = [
        DbDuplicateCandidate(
            existing_id=index,
            row_version=1,
            family_name=f"Candidate {index}",
            phone="0555123456",
            status="active",
        )
        for index in range(1, 12)
    ]

    scored, suggested_action, suggested_existing_id = _score_candidates_for_row(
        {"family_name": "Imported Person", "phone": "0555123456"},
        candidates,
    )

    assert suggested_action == "review_ambiguous"
    assert suggested_existing_id == 1
    assert len(scored) == 5


def test_duplicate_checker_keeps_ambiguous_decision_when_display_cap_is_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_IMPORT_MAX_DUPLICATE_CANDIDATES", "1")
    import_security_limits.cache_clear()
    candidates = [
        DbDuplicateCandidate(
            existing_id=18,
            row_version=5,
            family_name="Hasna Amrani",
            phone="0555123456",
            status="active",
        ),
        DbDuplicateCandidate(
            existing_id=24,
            row_version=3,
            family_name="Hasna Amranii",
            phone="0555123456",
            status="active",
        ),
    ]

    try:
        scored, suggested_action, suggested_existing_id = _score_candidates_for_row(
            {"family_name": "Hasna Amrani", "phone": "0555123456"},
            candidates,
        )
    finally:
        import_security_limits.cache_clear()

    assert len(scored) == 1
    assert suggested_action == "review_ambiguous"
    assert suggested_existing_id == 18
