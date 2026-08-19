# ruff: noqa: E402
from __future__ import annotations

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from core.importer.security import import_security_limits
from server.services import import_review_duplicates
from server.services.duplicate_checker import DbDuplicateCandidate, DbDuplicateMatch
from server.services.import_review_policy import UPDATE_EXISTING
from server.services.import_types import ReviewRowBuffer


def test_append_db_duplicate_reviews_shapes_suggested_update_payload() -> None:
    review_rows: list[dict[str, object]] = []

    import_review_duplicates.append_db_duplicate_reviews(
        entity_type="client",
        review_rows=review_rows,
        db_matches=[
            DbDuplicateMatch(
                row_index=7,
                field_name="phone",
                field_value="0551234567",
                total_candidate_count=1,
                candidates=[
                    DbDuplicateCandidate(
                        existing_id=42,
                        row_version=3,
                        family_name="Yacine",
                        phone="0551234567",
                        remarks="Existing row",
                        status="active",
                        match_confidence=0.973,
                        match_reasons=["same phone", "same name"],
                    )
                ],
                suggested_action=UPDATE_EXISTING,
                suggested_existing_id=42,
            )
        ],
        rows_by_index={
            7: {
                "data": {
                    "family_name": "Yacine",
                    "phone": "0551234567",
                    "remarks": "Incoming row",
                    "status": "active",
                },
                "original": {
                    "family_name": "Yacine",
                    "phone": "0551234567",
                    "remarks": "Original incoming row",
                    "status": "active",
                },
            }
        },
    )

    assert len(review_rows) == 1
    review_row = review_rows[0]
    assert review_row["suggested_action"] == UPDATE_EXISTING
    assert review_row["suggested_existing_id"] == 42
    assert review_row["candidate_version"] == 3
    assert review_row["suggested_confidence"] == 0.973
    assert review_row["suggested_reasons"] == ["same phone", "same name"]
    assert review_row["candidate_total_count"] == 1
    assert review_row["candidate_matches_truncated"] is False
    assert review_row["candidate_matches"] == [
        {
            "id": 42,
            "row_version": 3,
            "family_name": "Yacine",
            "phone": "0551234567",
            "remarks": "Existing row",
            "status": "active",
            "match_confidence": 0.973,
            "match_reasons": ["same phone", "same name"],
            "field_diffs": [
                {
                    "field": "remarks",
                    "incoming": "Incoming row",
                    "existing": "Existing row",
                }
            ],
            "field_diff": {
                "changed_mutable": [
                    {
                        "field": "remarks",
                        "incoming": "Incoming row",
                        "existing": "Existing row",
                    }
                ],
                "changed_immutable": [],
                "unchanged": [],
            },
        }
    ]
    assert review_row["field_diff"] == {
        "changed_mutable": [
            {
                "field": "remarks",
                "incoming": "Incoming row",
                "existing": "Existing row",
            }
        ],
        "changed_immutable": [],
        "unchanged": [],
    }
    assert review_row["review_fields"] == [
        {
            "field": "phone",
            "original": "0551234567",
            "normalized": "0551234567",
            "confidence": 0.973,
            "remark": "Suggested update: best match confidence 0.97 (same phone, same name)",
        }
    ]
    assert review_row["immutable_conflict"] is False


def test_append_db_duplicate_reviews_exposes_truthful_truncation_metadata() -> None:
    review_rows: list[dict[str, object]] = []

    import_review_duplicates.append_db_duplicate_reviews(
        entity_type="client",
        review_rows=review_rows,
        db_matches=[
            DbDuplicateMatch(
                row_index=9,
                field_name="phone",
                field_value="0551234009",
                total_candidate_count=7,
                candidates=[
                    DbDuplicateCandidate(
                        existing_id=42,
                        row_version=3,
                        family_name="Yacine",
                        phone="0551234009",
                        remarks="Existing row",
                        status="active",
                    )
                ],
                suggested_existing_id=42,
            )
        ],
        rows_by_index={
            9: {
                "data": {
                    "family_name": "Yacine",
                    "phone": "0551234009",
                    "remarks": "Incoming row",
                    "status": "active",
                }
            }
        },
    )

    assert len(review_rows) == 1
    review_row = review_rows[0]
    assert review_row["candidate_total_count"] == 7
    assert review_row["candidate_matches_truncated"] is True
    assert len(review_row["candidate_matches"]) == 1


def test_append_db_duplicate_reviews_increments_overflow_count_when_buffer_is_full(
    monkeypatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_IMPORT_MAX_REVIEW_ITEMS_EMERGENCY", "100")
    import_security_limits.cache_clear()
    review_rows = ReviewRowBuffer()

    try:
        for index in range(100):
            review_rows.append(
                {"row": index + 1, "entity_type": "client", "topology_side": "client_side"}
            )

        import_review_duplicates.append_db_duplicate_reviews(
            entity_type="client",
            review_rows=review_rows,
            db_matches=[
                DbDuplicateMatch(
                    row_index=101,
                    field_name="phone",
                    field_value="0550000101",
                    candidates=[
                        DbDuplicateCandidate(
                            existing_id=77,
                            row_version=5,
                            family_name="Overflow",
                            phone="0550000101",
                            remarks="Existing row",
                            status="active",
                        )
                    ],
                    suggested_existing_id=77,
                )
            ],
            rows_by_index={
                101: {
                    "data": {
                        "family_name": "Overflow",
                        "phone": "0550000101",
                        "remarks": "Incoming row",
                        "status": "active",
                    }
                }
            },
        )

        assert len(review_rows) == 100
        assert review_rows.overflow_count == 1
    finally:
        review_rows.cleanup()
        import_security_limits.cache_clear()


def test_append_db_duplicate_reviews_propagates_immutable_conflict(monkeypatch) -> None:
    monkeypatch.setattr(
        import_review_duplicates,
        "_build_candidate_field_diffs",
        lambda _row_data, *, candidate: [
            {
                "field": "row_version",
                "incoming": "8",
                "existing": str(candidate.row_version),
            }
        ],
    )
    review_rows: list[dict[str, object]] = []

    import_review_duplicates.append_db_duplicate_reviews(
        entity_type="client",
        review_rows=review_rows,
        db_matches=[
            DbDuplicateMatch(
                row_index=12,
                field_name="phone",
                field_value="0559990012",
                candidates=[
                    DbDuplicateCandidate(
                        existing_id=11,
                        row_version=3,
                        family_name="Conflict",
                        phone="0559990012",
                        remarks="Existing row",
                        status="active",
                    )
                ],
                suggested_existing_id=11,
            )
        ],
        rows_by_index={
            12: {
                "data": {
                    "family_name": "Conflict",
                    "phone": "0559990012",
                    "remarks": "Incoming row",
                    "status": "active",
                }
            }
        },
    )

    assert len(review_rows) == 1
    review_row = review_rows[0]
    assert review_row["immutable_conflict"] is True
    assert review_row["field_diff"] == {
        "changed_mutable": [],
        "changed_immutable": [
            {
                "field": "row_version",
                "incoming": "8",
                "existing": "3",
            }
        ],
        "unchanged": [],
    }
