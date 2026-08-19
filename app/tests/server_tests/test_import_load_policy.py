from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from core.contracts.import_batch_refs import CreatedRowRef  # noqa: E402
from server.services.import_load_policy import (  # noqa: E402
    classify_child_anchor,
    evaluate_orphan_threshold,
    flush_root_entries_with_conflict_isolation,
    is_unique_violation,
)
from server.services.import_types import ImportLoadOutcome  # noqa: E402


class _MutableError(RuntimeError):
    pass


class _SqlStateError(RuntimeError):
    def __init__(self, message: str, *, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class _UniqueViolation(RuntimeError):
    sqlstate = "23505"


def test_is_unique_violation_only_accepts_sqlstate_23505() -> None:
    duplicate_text_fk = _SqlStateError(
        "duplicate key value violates unique constraint",
        sqlstate="23503",
    )
    no_sqlstate_duplicate = RuntimeError("duplicate key value violates unique constraint")
    wrapped = _MutableError("outer duplicate wrapper")
    wrapped.__cause__ = _SqlStateError("inner unique violation", sqlstate="23505")
    wrapped_orig = _MutableError("outer orig wrapper")
    wrapped_orig.orig = SimpleNamespace(sqlstate="23505")

    assert is_unique_violation(_SqlStateError("unique violation", sqlstate="23505")) is True
    assert is_unique_violation(wrapped) is True
    assert is_unique_violation(wrapped_orig) is True
    assert is_unique_violation(duplicate_text_fk) is False
    assert is_unique_violation(no_sqlstate_duplicate) is False


def test_flush_root_entries_with_conflict_isolation_includes_failed_attempt_db_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_values = iter([0.0, 1.0, 1.5, 2.0, 2.5, 3.0])
    monkeypatch.setattr(
        "server.services.import_load_policy.time.monotonic",
        lambda: next(monotonic_values),
    )

    created_ids: list[int] = []
    appended_rows: list[int] = []

    def _fake_insert_batch(
        *,
        batch_rows: list[dict[str, object]],
        source_ordinals: list[int],
        **_kwargs: object,
    ) -> list[CreatedRowRef]:
        if len(batch_rows) > 1:
            raise _UniqueViolation("root batch conflict")
        return [
            CreatedRowRef(
                source_ordinal=int(source_ordinals[0]),
                created_id=9000 + int(str(batch_rows[0].get("phone", "0"))[-1]),
            )
        ]

    def _on_rows_inserted(
        rows: list[CreatedRowRef],
        _entries: list[dict[str, object]],
    ) -> None:
        created_ids.extend(int(row.created_id) for row in rows)

    result = flush_root_entries_with_conflict_isolation(
        write_session=object(),
        entity_type="client",
        batch_entries=[
            {
                "row": 1,
                "data": {"phone": "0555001001"},
                "anchor_keys": ["phone:0555001001"],
            },
            {
                "row": 2,
                "data": {"phone": "0555001002"},
                "anchor_keys": ["phone:0555001002"],
            },
        ],
        load_outcome=ImportLoadOutcome(),
        on_rows_inserted=_on_rows_inserted,
        append_leaf_error=lambda entry: appended_rows.append(int(entry["row"])),
        insert_batch_fn=_fake_insert_batch,
    )

    assert created_ids == [9001, 9002]
    assert result.created_ids == [9001, 9002]
    assert result.skipped_count == 0
    assert result.db_duration == pytest.approx(2.0)
    assert appended_rows == []


def test_classify_child_anchor_preserves_orphan_and_ambiguous_wording() -> None:
    resolved = classify_child_anchor(original_anchor_id=11, resolved_anchor_id=11)
    orphan = classify_child_anchor(original_anchor_id=0, resolved_anchor_id=0)
    ambiguous = classify_child_anchor(original_anchor_id=-1, resolved_anchor_id=0)

    assert resolved.is_resolved is True
    assert orphan.kind == "orphan"
    assert orphan.user_error == "Planned child row lost its parent anchor during load."
    assert orphan.internal_error == "Planned child row lost its parent anchor during load."
    assert ambiguous.kind == "ambiguous_parent"
    assert ambiguous.user_error == "Planned child row had an ambiguous parent and was not anchored."
    assert (
        ambiguous.internal_error
        == "A planned child row had an ambiguous parent and was not anchored."
    )


@pytest.mark.parametrize(
    ("orphan_count", "total_count", "expected_ratio", "expected_hard_fail"),
    [
        (0, 10, 0.0, False),
        (1, 10, 0.1, False),
        (2, 10, 0.2, True),
    ],
)
def test_evaluate_orphan_threshold_boundary_cases(
    orphan_count: int,
    total_count: int,
    expected_ratio: float,
    expected_hard_fail: bool,
) -> None:
    decision = evaluate_orphan_threshold(
        orphan_count=orphan_count,
        total_count=total_count,
    )

    assert decision.orphan_ratio == pytest.approx(expected_ratio)
    assert decision.hard_fail is expected_hard_fail
