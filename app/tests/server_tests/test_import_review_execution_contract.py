from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

import server.services.import_review_resolution as import_review_resolution_module  # noqa: E402
import server.services.import_review_resolution_creates as import_review_resolution_creates_module  # noqa: E402
import server.services.import_review_row_actions as import_review_row_actions_module  # noqa: E402
from core.contracts.import_batch_refs import CreatedRowRef  # noqa: E402
from core.data.errors import ConflictError  # noqa: E402
from server.services.import_review_created_rows import (  # noqa: E402
    ReviewCorrectionCreateBatch,
    call_insert_review_corrections,
)
from server.services.import_review_execution_service import (  # noqa: E402
    ImportReviewConflictError,
    apply_review_resolutions,
)
from server.services.import_review_resolution_creates import (  # noqa: E402
    insert_review_correction_batches_impl,
)
from server.services.import_review_row_actions import (  # noqa: E402
    ReviewResolutionState,
)


def _created_row_refs_for_rows(
    rows: list[dict[str, object]],
    *,
    start_id: int = 9000,
    reverse: bool = False,
) -> list[CreatedRowRef]:
    created_rows = [
        CreatedRowRef(source_ordinal=index, created_id=start_id + index + 1)
        for index, _row in enumerate(rows)
    ]
    return list(reversed(created_rows)) if reverse else created_rows


def _created_row_refs_for_batches(
    batches: list[ReviewCorrectionCreateBatch],
    *,
    start_id: int = 9000,
    reverse: bool = False,
) -> dict[str, list[CreatedRowRef]]:
    return {
        batch.entity_type: _created_row_refs_for_rows(
            list(batch.corrected_rows),
            start_id=start_id + (index * 100),
            reverse=reverse,
        )
        for index, batch in enumerate(batches)
    }


def test_apply_review_resolutions_supports_same_row_multiple_entity_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePipeline:
        def __init__(
            self,
            *,
            entity_type: str,
            column_types: dict[str, str],
            field_metadata: dict[str, dict[str, object]] | None = None,
        ) -> None:
            self.entity_type = entity_type
            self.column_types = column_types
            self.field_metadata = field_metadata or {}

        def normalize_row(self, row_data: dict[str, object]) -> SimpleNamespace:
            return SimpleNamespace(
                needs_review=False,
                data=dict(row_data),
                remarks=[],
                review_fields=[],
                recoverability_class="review_recoverable",
                recovered_fields=[],
                recovery_candidates=[],
                blocking_reasons=[],
            )

    monkeypatch.setattr(
        "server.services.import_review_execution_service.NormalizationPipeline",
        _FakePipeline,
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.validate_row",
        lambda row, _entity_type: (dict(row), []),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.insert_review_correction_batches",
        lambda *, batches, **_kwargs: _created_row_refs_for_batches(
            list(batches),
            start_id=8800,
        ),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.detect_create_conflicts",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_learning_signals",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_dead_letter_rows",
        lambda _rows: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.refresh_agency_profile",
        lambda **_kwargs: None,
    )

    review_rows = [
        {
            "row": 1,
            "entity_type": "client",
            "data": {"family_name": "Yacine", "phone": "0555001001"},
            "original": {"family_name": "Yacine", "phone": "0555001001"},
            "candidate_matches": [],
            "review_fields": [],
            "remarks": [],
        },
        {
            "row": 1,
            "entity_type": "demande",
            "data": {"action": "buy", "type": "apartment"},
            "original": {"action": "buy", "type": "apartment"},
            "candidate_matches": [],
            "review_fields": [],
            "remarks": [],
        },
    ]

    result = apply_review_resolutions(
        job_id="job-1",
        entity_type="client",
        review_rows=review_rows,
        corrections={},
        decisions={
            "1:client": {"action": "create_new", "entity_type": "client"},
            "1:demande": {"action": "create_new", "entity_type": "demande"},
        },
        skip_rows=[],
        user_id=9,
        agency_id=12,
    )

    assert result["created_count"] == 2
    assert result["created_entity_counts"] == {"client": 1, "demande": 1}
    assert result["still_review"] == []


def test_insert_review_correction_batches_uses_one_transaction_for_all_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _FakeTransaction:
        def __enter__(self) -> str:
            events.append("enter")
            return "write-session"

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            events.append("rollback" if exc_type is not None else "commit")

    class _FakeUow:
        def transaction(self, *, actor: str) -> _FakeTransaction:
            events.append(f"transaction:{actor}")
            return _FakeTransaction()

    def _insert_batch_refs(*, entity_type: str, batch_rows: list[dict[str, object]], **_kwargs):
        events.append(f"insert:{entity_type}")
        if entity_type == "demande":
            raise ConflictError("demande failed")
        return _created_row_refs_for_rows(batch_rows, start_id=5000)

    monkeypatch.setattr(import_review_resolution_creates_module, "get_uow", lambda: _FakeUow())
    monkeypatch.setattr(
        import_review_resolution_creates_module, "insert_batch_refs", _insert_batch_refs
    )
    monkeypatch.setattr(
        import_review_resolution_creates_module,
        "schedule_review_corrections_after_commit",
        lambda **_kwargs: events.append("schedule"),
    )

    with pytest.raises(ConflictError):
        insert_review_correction_batches_impl(
            job_id="job-atomic",
            batches=[
                ReviewCorrectionCreateBatch(
                    entity_type="client",
                    corrected_rows=[{"family_name": "A"}],
                ),
                ReviewCorrectionCreateBatch(
                    entity_type="demande",
                    corrected_rows=[{"action": "buy"}],
                ),
            ],
            user_id=7,
            agency_id=12,
        )

    assert events.count("enter") == 1
    assert "insert:client" in events
    assert "insert:demande" in events
    assert "schedule" in events
    assert "commit" not in events
    assert "rollback" in events


def test_call_insert_review_corrections_passes_job_id_when_callable_declares_it() -> None:
    captured: dict[str, object] = {}

    def _insert_review_corrections(
        *,
        job_id: str,
        entity_type: str,
        corrected_rows: list[dict[str, object]],
        user_id: int,
        agency_id: int,
    ) -> list[CreatedRowRef]:
        captured.update(
            {
                "job_id": job_id,
                "entity_type": entity_type,
                "corrected_rows": list(corrected_rows),
                "user_id": user_id,
                "agency_id": agency_id,
            }
        )
        return _created_row_refs_for_rows(corrected_rows, start_id=9000)

    result = call_insert_review_corrections(
        insert_review_corrections_fn=_insert_review_corrections,
        job_id="job-explicit",
        entity_type="client",
        corrected_rows=[{"family_name": "Yacine"}],
        user_id=7,
        agency_id=12,
    )

    assert result == [CreatedRowRef(source_ordinal=0, created_id=9001)]
    assert captured == {
        "job_id": "job-explicit",
        "entity_type": "client",
        "corrected_rows": [{"family_name": "Yacine"}],
        "user_id": 7,
        "agency_id": 12,
    }


def test_call_insert_review_corrections_rejects_callable_without_job_id() -> None:
    def _insert_review_corrections(
        *,
        entity_type: str,
        corrected_rows: list[dict[str, object]],
        user_id: int,
        agency_id: int,
    ) -> list[CreatedRowRef]:
        return _created_row_refs_for_rows(corrected_rows, start_id=9100)

    with pytest.raises(TypeError, match="job_id"):
        call_insert_review_corrections(
            insert_review_corrections_fn=_insert_review_corrections,
            job_id="job-strict",
            entity_type="demande",
            corrected_rows=[{"action": "buy"}],
            user_id=9,
            agency_id=18,
        )


def test_call_insert_review_corrections_passes_job_id_through_var_kwargs() -> None:
    captured: dict[str, object] = {}

    def _insert_review_corrections(**kwargs: object) -> list[CreatedRowRef]:
        captured.update(kwargs)
        return [
            CreatedRowRef(source_ordinal=1, created_id=9202),
            CreatedRowRef(source_ordinal=0, created_id=9201),
        ]

    result = call_insert_review_corrections(
        insert_review_corrections_fn=_insert_review_corrections,
        job_id="job-var-kwargs",
        entity_type="offer",
        corrected_rows=[{"price": 1000}, {"price": 2000}],
        user_id=11,
        agency_id=21,
    )

    assert result == [
        CreatedRowRef(source_ordinal=1, created_id=9202),
        CreatedRowRef(source_ordinal=0, created_id=9201),
    ]
    assert captured["job_id"] == "job-var-kwargs"
    assert captured["entity_type"] == "offer"
    assert captured["corrected_rows"] == [{"price": 1000}, {"price": 2000}]


def test_call_insert_review_corrections_propagates_real_type_error_from_callable_body() -> None:
    def _insert_review_corrections(**_kwargs: object) -> list[CreatedRowRef]:
        raise TypeError("inner seam failure")

    with pytest.raises(TypeError, match="inner seam failure"):
        call_insert_review_corrections(
            insert_review_corrections_fn=_insert_review_corrections,
            job_id="job-type-error",
            entity_type="client",
            corrected_rows=[{"family_name": "Yacine"}],
            user_id=3,
            agency_id=5,
        )


def test_apply_review_resolutions_returns_structured_conflict_on_batch_insert_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePipeline:
        def __init__(
            self,
            *,
            entity_type: str,
            column_types: dict[str, str],
            field_metadata: dict[str, dict[str, object]] | None = None,
        ) -> None:
            self.entity_type = entity_type
            self.column_types = column_types
            self.field_metadata = field_metadata or {}

        def normalize_row(self, row_data: dict[str, object]) -> SimpleNamespace:
            return SimpleNamespace(
                needs_review=False,
                data=dict(row_data),
                remarks=[],
                review_fields=[],
                recoverability_class="review_recoverable",
                recovered_fields=[],
                recovery_candidates=[],
                blocking_reasons=[],
            )

    monkeypatch.setattr(
        "server.services.import_review_execution_service.NormalizationPipeline",
        _FakePipeline,
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.validate_row",
        lambda row, _entity_type: (dict(row), []),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.detect_create_conflicts",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.insert_review_correction_batches",
        lambda **_kwargs: (_ for _ in ()).throw(
            ConflictError("duplicate key value violates unique constraint")
        ),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_learning_signals",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_dead_letter_rows",
        lambda _rows: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.refresh_agency_profile",
        lambda **_kwargs: None,
    )

    review_rows = [
        {
            "row": 14,
            "entity_type": "client",
            "data": {"family_name": "Yacine", "phone": "0555001001"},
            "original": {"family_name": "Yacine", "phone": "0555001001"},
            "candidate_matches": [],
            "review_fields": [],
            "remarks": [],
        },
        {
            "row": 15,
            "entity_type": "client",
            "data": {"family_name": "Yacine", "phone": "0555001001"},
            "original": {"family_name": "Yacine", "phone": "0555001001"},
            "candidate_matches": [],
            "review_fields": [],
            "remarks": [],
        },
    ]

    with pytest.raises(ImportReviewConflictError) as exc_info:
        apply_review_resolutions(
            job_id="job-2",
            entity_type="client",
            review_rows=review_rows,
            corrections={},
            decisions={
                "14": {"action": "create_new"},
                "15": {"action": "create_new"},
            },
            skip_rows=[],
            user_id=9,
            agency_id=12,
        )

    assert {int(item["row"]) for item in exc_info.value.row_conflicts} == {14, 15}
    assert all(
        str(item["conflict_type"]) == "duplicate_phone" for item in exc_info.value.row_conflicts
    )


def test_apply_review_resolutions_uses_monkeypatched_facade_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _FakePipeline:
        def __init__(
            self,
            *,
            entity_type: str,
            column_types: dict[str, str],
            field_metadata: dict[str, dict[str, object]] | None = None,
        ) -> None:
            _ = (entity_type, column_types, field_metadata)
            calls.append("pipeline")

        def normalize_row(self, row_data: dict[str, object]) -> SimpleNamespace:
            calls.append("normalize_row")
            return SimpleNamespace(
                needs_review=False,
                data=dict(row_data),
                remarks=[],
                review_fields=[],
                recoverability_class="review_recoverable",
                recovered_fields=[],
                recovery_candidates=[],
                blocking_reasons=[],
            )

    monkeypatch.setattr(
        "server.services.import_review_execution_service.NormalizationPipeline",
        _FakePipeline,
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.validate_row",
        lambda row, _entity_type: (calls.append("validate_row") or True) and (dict(row), []),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.detect_create_conflicts",
        lambda **_kwargs: (calls.append("detect_conflicts") or []),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.insert_review_correction_batches",
        lambda **_kwargs: (
            calls.append("insert_review_correction_batches")
            or {"client": [CreatedRowRef(source_ordinal=0, created_id=1)]}
        ),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_learning_signals",
        lambda **_kwargs: (calls.append("record_learning_signals") or {}),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_dead_letter_rows",
        lambda _rows: (calls.append("record_dead_letter_rows") or {}),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.refresh_agency_profile",
        lambda **_kwargs: calls.append("refresh_agency_profile"),
    )

    result = apply_review_resolutions(
        job_id="job-3",
        entity_type="client",
        review_rows=[
            {
                "row": 1,
                "entity_type": "client",
                "data": {"family_name": "Yacine", "phone": "0555001001"},
                "original": {"family_name": "Yacine", "phone": "0555001001"},
                "candidate_matches": [],
                "review_fields": [],
                "remarks": [],
            }
        ],
        corrections={},
        decisions={"1": {"action": "create_new", "entity_type": "client"}},
        skip_rows=[],
        user_id=9,
        agency_id=12,
    )

    assert result["created_count"] == 1
    assert "pipeline" in calls
    assert "normalize_row" in calls
    assert "validate_row" in calls
    assert "detect_conflicts" in calls
    assert "insert_review_correction_batches" in calls
    assert "record_learning_signals" in calls
    assert "record_dead_letter_rows" in calls
    assert "refresh_agency_profile" in calls


def test_still_review_row_rejects_metadata_key_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        import_review_row_actions_module,
        "review_entry_metadata",
        lambda _review_entry: {"remarks": ["overlap"]},
    )

    with pytest.raises(ValueError, match="protected review-row keys: remarks"):
        import_review_row_actions_module._still_review_row(
            row_num=1,
            row_data={"family_name": "Yacine"},
            original={"family_name": "Yacine"},
            review_fields=[],
            remarks=["Needs review"],
            candidate_matches=[],
            review_entry={"topology_side": "client_side"},
            entity_type="client",
        )


def test_apply_pending_updates_stops_after_first_occ_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def _upsert_client(payload: dict[str, object], *, actor: str) -> None:
        calls.append(int(payload["id"]))
        assert actor == "import_review:31"
        if int(payload["id"]) == 202:
            raise ConflictError(
                "row version conflict",
                current_version=9,
                current_record={"id": 202, "family_name": "Existing"},
            )

    monkeypatch.setattr("server.services.clients.upsert_client", _upsert_client)

    state = ReviewResolutionState(
        pending_updates=[
            {
                "row_num": 1,
                "entity_type": "client",
                "validated_row": {"family_name": "First"},
                "existing_id": 101,
                "row_version": 3,
                "review_entry": {"remarks": []},
                "before_payload": {},
                "diff_payload": {},
                "correction_payload": {},
            },
            {
                "row_num": 2,
                "entity_type": "client",
                "validated_row": {"family_name": "Second"},
                "existing_id": 202,
                "row_version": 4,
                "review_entry": {"remarks": []},
                "before_payload": {},
                "diff_payload": {},
                "correction_payload": {},
            },
            {
                "row_num": 3,
                "entity_type": "client",
                "validated_row": {"family_name": "Third"},
                "existing_id": 303,
                "row_version": 5,
                "review_entry": {"remarks": []},
                "before_payload": {},
                "diff_payload": {},
                "correction_payload": {},
            },
        ]
    )

    with pytest.raises(ImportReviewConflictError) as exc_info:
        import_review_resolution_module._apply_pending_updates(state=state, user_id=31)

    assert calls == [101, 202]
    assert exc_info.value.row_conflicts == [
        {
            "row": 2,
            "entity_type": "client",
            "conflict_type": "row_version_conflict",
            "field": "row_version",
            "existing_id": 202,
            "existing_summary": "{'id': 202, 'family_name': 'Existing'}",
            "suggested_action": "review",
        }
    ]


def test_apply_review_resolutions_raises_when_create_batch_returns_fewer_refs_than_pending_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePipeline:
        def __init__(
            self,
            *,
            entity_type: str,
            column_types: dict[str, str],
            field_metadata: dict[str, dict[str, object]] | None = None,
        ) -> None:
            self.entity_type = entity_type
            self.column_types = column_types
            self.field_metadata = field_metadata or {}

        def normalize_row(self, row_data: dict[str, object]) -> SimpleNamespace:
            return SimpleNamespace(
                needs_review=False,
                data=dict(row_data),
                remarks=[],
                review_fields=[],
                recoverability_class="review_recoverable",
                recovered_fields=[],
                recovery_candidates=[],
                blocking_reasons=[],
            )

    monkeypatch.setattr(
        "server.services.import_review_execution_service.NormalizationPipeline",
        _FakePipeline,
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.validate_row",
        lambda row, _entity_type: (dict(row), []),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.detect_create_conflicts",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.insert_review_correction_batches",
        lambda **_kwargs: {"client": [CreatedRowRef(source_ordinal=0, created_id=9901)]},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_learning_signals",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_dead_letter_rows",
        lambda _rows: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.refresh_agency_profile",
        lambda **_kwargs: None,
    )

    review_rows = [
        {
            "row": 1,
            "entity_type": "client",
            "data": {"family_name": "Alpha", "phone": "0555001001"},
            "original": {"family_name": "Alpha", "phone": "0555001001"},
            "candidate_matches": [],
            "review_fields": [],
            "remarks": [],
        },
        {
            "row": 2,
            "entity_type": "client",
            "data": {"family_name": "Beta", "phone": "0555001002"},
            "original": {"family_name": "Beta", "phone": "0555001002"},
            "candidate_matches": [],
            "review_fields": [],
            "remarks": [],
        },
    ]

    with pytest.raises(ImportReviewConflictError) as exc_info:
        apply_review_resolutions(
            job_id="job-cardinality",
            entity_type="client",
            review_rows=review_rows,
            corrections={},
            decisions={
                "1": {"action": "create_new", "entity_type": "client"},
                "2": {"action": "create_new", "entity_type": "client"},
            },
            skip_rows=[],
            user_id=7,
            agency_id=12,
        )
    assert exc_info.value.row_conflicts[0]["conflict_type"] == "create_result_mismatch"


def test_apply_review_resolutions_accepts_out_of_order_created_row_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePipeline:
        def __init__(
            self,
            *,
            entity_type: str,
            column_types: dict[str, str],
            field_metadata: dict[str, dict[str, object]] | None = None,
        ) -> None:
            self.entity_type = entity_type
            self.column_types = column_types
            self.field_metadata = field_metadata or {}

        def normalize_row(self, row_data: dict[str, object]) -> SimpleNamespace:
            return SimpleNamespace(
                needs_review=False,
                data=dict(row_data),
                remarks=[],
                review_fields=[],
                recoverability_class="review_recoverable",
                recovered_fields=[],
                recovery_candidates=[],
                blocking_reasons=[],
            )

    monkeypatch.setattr(
        "server.services.import_review_execution_service.NormalizationPipeline",
        _FakePipeline,
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.validate_row",
        lambda row, _entity_type: (dict(row), []),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.detect_create_conflicts",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.insert_review_correction_batches",
        lambda *, batches, **_kwargs: _created_row_refs_for_batches(
            list(batches),
            start_id=9800,
            reverse=True,
        ),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_learning_signals",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_dead_letter_rows",
        lambda _rows: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.refresh_agency_profile",
        lambda **_kwargs: None,
    )

    result = apply_review_resolutions(
        job_id="job-out-of-order",
        entity_type="client",
        review_rows=[
            {
                "row": 1,
                "entity_type": "client",
                "data": {"family_name": "Alpha", "phone": "0555001001"},
                "original": {"family_name": "Alpha", "phone": "0555001001"},
                "candidate_matches": [],
                "review_fields": [],
                "remarks": [],
            },
            {
                "row": 2,
                "entity_type": "client",
                "data": {"family_name": "Beta", "phone": "0555001002"},
                "original": {"family_name": "Beta", "phone": "0555001002"},
                "candidate_matches": [],
                "review_fields": [],
                "remarks": [],
            },
        ],
        corrections={},
        decisions={
            "1": {"action": "create_new", "entity_type": "client"},
            "2": {"action": "create_new", "entity_type": "client"},
        },
        skip_rows=[],
        user_id=7,
        agency_id=12,
    )

    assert result["created_count"] == 2
    assert [int(entry["row"]) for entry in result["audit_entries"]] == [1, 2]


def test_apply_review_resolutions_raises_when_create_batch_returns_duplicate_source_ordinals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePipeline:
        def __init__(
            self,
            *,
            entity_type: str,
            column_types: dict[str, str],
            field_metadata: dict[str, dict[str, object]] | None = None,
        ) -> None:
            self.entity_type = entity_type
            self.column_types = column_types
            self.field_metadata = field_metadata or {}

        def normalize_row(self, row_data: dict[str, object]) -> SimpleNamespace:
            return SimpleNamespace(
                needs_review=False,
                data=dict(row_data),
                remarks=[],
                review_fields=[],
                recoverability_class="review_recoverable",
                recovered_fields=[],
                recovery_candidates=[],
                blocking_reasons=[],
            )

    monkeypatch.setattr(
        "server.services.import_review_execution_service.NormalizationPipeline",
        _FakePipeline,
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.validate_row",
        lambda row, _entity_type: (dict(row), []),
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.detect_create_conflicts",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.insert_review_correction_batches",
        lambda **_kwargs: {
            "client": [
                CreatedRowRef(source_ordinal=0, created_id=9901),
                CreatedRowRef(source_ordinal=0, created_id=9902),
            ]
        },
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_learning_signals",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.record_dead_letter_rows",
        lambda _rows: {},
    )
    monkeypatch.setattr(
        "server.services.import_review_execution_service.refresh_agency_profile",
        lambda **_kwargs: None,
    )

    with pytest.raises(ImportReviewConflictError) as exc_info:
        apply_review_resolutions(
            job_id="job-duplicate-ordinals",
            entity_type="client",
            review_rows=[
                {
                    "row": 1,
                    "entity_type": "client",
                    "data": {"family_name": "Alpha", "phone": "0555001001"},
                    "original": {"family_name": "Alpha", "phone": "0555001001"},
                    "candidate_matches": [],
                    "review_fields": [],
                    "remarks": [],
                },
                {
                    "row": 2,
                    "entity_type": "client",
                    "data": {"family_name": "Beta", "phone": "0555001002"},
                    "original": {"family_name": "Beta", "phone": "0555001002"},
                    "candidate_matches": [],
                    "review_fields": [],
                    "remarks": [],
                },
            ],
            corrections={},
            decisions={
                "1": {"action": "create_new", "entity_type": "client"},
                "2": {"action": "create_new", "entity_type": "client"},
            },
            skip_rows=[],
            user_id=7,
            agency_id=12,
        )
    assert exc_info.value.row_conflicts[0]["conflict_type"] == "create_result_mismatch"
