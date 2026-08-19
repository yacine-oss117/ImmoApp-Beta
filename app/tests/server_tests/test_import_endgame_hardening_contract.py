from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.utils import timezone

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.services import import_location_normalizer as location_provider  # noqa: E402
from server.services import import_review_metadata_safety as review_metadata_safety  # noqa: E402
from server.services import work_admission  # noqa: E402
from server.services.cache_layers import AdaptiveLocalCache  # noqa: E402
from server.services.import_finalize_service import (  # noqa: E402
    _workflow_duration_seconds,
    finalize_distributed_import_job,
)
from server.services.import_review_collector import ImportReviewCollector  # noqa: E402
from server.services.import_review_compatibility import build_compatibility_review_row  # noqa: E402
from server.services.import_review_conflicts import detect_create_conflicts  # noqa: E402
from server.services.import_review_db_state import _grouped_review_state  # noqa: E402
from server.services.import_review_metadata_safety import project_review_metadata  # noqa: E402
from server.services.import_ui_summary import classify_review_issue  # noqa: E402
from server.services.import_workflow_dispatch import rollup_workflow_progress  # noqa: E402


def test_progress_rollup_keeps_review_overflow_out_of_generic_error_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[dict[str, object]] = []
    job = SimpleNamespace(
        result_summary={"row_count": 10},
        progress=0,
        progress_detail={},
        save=lambda **kwargs: saved.append(dict(kwargs)),
    )
    phase = SimpleNamespace(
        metrics_payload={"processed_count": 5, "review_count": 1, "error_count": 2},
        status="completed",
        phase="load",
    )
    monkeypatch.setattr(
        "server.services.import_workflow_dispatch.job_topology",
        lambda _job: SimpleNamespace(bundle_mode="single_entity"),
    )
    monkeypatch.setattr(
        "server.services.import_workflow_dispatch.aggregate_review_overflow_count",
        lambda **_kwargs: 3,
    )

    rollup_workflow_progress(
        job=job,
        workflow={
            "prepare_completed": True,
            "prepare_counts": {"review_count": 4, "error_count": 1},
        },
        phases=[phase],
    )

    assert job.progress_detail["rows_review"] == 8
    assert job.progress_detail["review_overflow_count"] == 3
    assert job.progress_detail["error_count"] == 3
    assert saved


def test_import_review_collector_context_manager_cleans_spool_on_exception() -> None:
    with pytest.raises(RuntimeError):
        with ImportReviewCollector(max_items_emergency=5) as collector:
            spool_dir = collector.spool_path.parent
            assert spool_dir.exists()
            collector.append({"row": 1})
            raise RuntimeError("planning failed")

    assert not spool_dir.exists()


def test_finalize_distributed_import_job_cleans_review_rows_once_on_rollup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeReviewRows:
        def __init__(self) -> None:
            self.cleanup_calls = 0

        def cleanup(self) -> None:
            self.cleanup_calls += 1

    review_rows = _FakeReviewRows()
    expected_error = RuntimeError("review rollup failed")

    monkeypatch.setattr(
        "server.services.import_chunk_workflow.workflow_payload",
        lambda _job: {"params": {}, "prepare_counts": {}},
    )
    monkeypatch.setattr(
        "server.services.import_finalize_service._rollup_load_phase",
        lambda *, job: SimpleNamespace(result=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "server.services.import_chunk_workflow.collected_review_rows",
        lambda _job: (review_rows, []),
    )
    monkeypatch.setattr(
        "server.services.import_finalize_service._rollup_review_phase",
        lambda **_kwargs: (_ for _ in ()).throw(expected_error),
    )

    with pytest.raises(RuntimeError, match="review rollup failed"):
        finalize_distributed_import_job(job=SimpleNamespace(detected_entity="client"), user_id=7)

    assert review_rows.cleanup_calls == 1


def test_adaptive_local_cache_deep_clones_nested_payloads() -> None:
    cache = AdaptiveLocalCache()
    payload = {"items": [{"nested": ["a"]}], "total": 1}
    assert cache.set(
        cache_name="clients_count",
        key="nested",
        payload=payload,
        tenant_key="agency:1",
        policy_name="clients_count",
        ttl_seconds=60,
        admit_after_hits=1,
        max_entry_bytes=262144,
    )

    first = cache.get(cache_name="clients_count", key="nested")
    assert isinstance(first, dict)
    first["items"][0]["nested"].append("mutated")  # type: ignore[index,union-attr]

    second = cache.get(cache_name="clients_count", key="nested")
    assert second == {"items": [{"nested": ["a"]}], "total": 1}


def test_adaptive_local_cache_sweeps_admission_counts_and_compacts_heap() -> None:
    cache = AdaptiveLocalCache()
    cache._admission_counts = {f"k{i}": (1.0, 1) for i in range(1500)}
    cache._sweep_admission_counts(120.0)
    assert len(cache._admission_counts) == 0

    for _index in range(1200):
        assert cache.set(
            cache_name="clients_count",
            key="same",
            payload={"items": [1]},
            tenant_key="agency:1",
            policy_name="clients_count",
            ttl_seconds=60,
            admit_after_hits=1,
            max_entry_bytes=262144,
        )
    assert len(cache._entries) == 1
    assert len(cache._expiry_heap) <= max(len(cache._entries) * 2, len(cache._entries) + 1024)


def test_active_work_counts_failure_returns_degraded_pressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenUow:
        def session(self):
            raise RuntimeError("db unavailable")

    logged: list[str] = []
    monkeypatch.setattr(work_admission, "get_uow", lambda: _BrokenUow())
    monkeypatch.setattr(
        work_admission.logger,
        "exception",
        lambda message, *args, **kwargs: logged.append(str(message)),
    )
    monkeypatch.setattr(
        work_admission.tenant_resource_governor,
        "governor_backend_available",
        lambda: False,
    )
    monkeypatch.setattr(
        work_admission.match_runtime_profile,
        "effective_profile_state",
        lambda: SimpleNamespace(profile="red"),
    )

    counts = work_admission.active_work_counts()
    decision = work_admission.admit_match_all(agency_id=1, task_name="matches_all")

    assert counts["degraded"] == 1
    assert decision.allowed is False
    assert any("Failed to read active work counts" in message for message in logged)


def test_distributed_workflow_duration_uses_started_at_wall_clock() -> None:
    started_at = timezone.now() - timedelta(seconds=7)

    duration = _workflow_duration_seconds(
        {"started_at": started_at.isoformat(), "started_monotonic": 0.0}
    )

    assert duration >= 6.0


def test_shared_location_normalizer_constructs_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location_provider._reset_shared_location_normalizer_for_tests()
    constructed = 0
    constructed_lock = threading.Lock()

    class _FakeNormalizer:
        def __init__(self) -> None:
            nonlocal constructed
            with constructed_lock:
                constructed += 1

    monkeypatch.setattr(location_provider, "LocationNormalizer", _FakeNormalizer)
    results: list[object] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(location_provider.shared_location_normalizer())
        )
        for _index in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    assert constructed == 1
    assert len({id(value) for value in results}) == 1
    location_provider._reset_shared_location_normalizer_for_tests()


def test_review_metadata_projection_keeps_unknown_metadata_nested() -> None:
    projected = project_review_metadata(
        {
            "row": 7,
            "entity_type": "client",
            "status": "pending",
            "metadata": {"existing": "kept", "safe": "old"},
        },
        {
            "row": 99,
            "entity_type": "listing",
            "status": "resolved",
            "safe": "new",
            "new_key": "value",
        },
    )

    assert projected["row"] == 7
    assert projected["entity_type"] == "client"
    assert projected["status"] == "pending"
    assert "safe" not in projected
    assert "new_key" not in projected
    assert projected["metadata"] == {"existing": "kept", "safe": "new", "new_key": "value"}


def test_review_metadata_projection_uses_empty_promotion_allowlist() -> None:
    assert review_metadata_safety.PROMOTED_REVIEW_METADATA_KEYS == frozenset()


def test_compatibility_review_row_metadata_cannot_shadow_core_fields() -> None:
    item = SimpleNamespace(
        row_ordinal=3,
        normalized_data={},
        raw_data={},
        entity_type="client",
        topology_side="unknown",
        suggested_action="review_ambiguous",
        suggested_existing_id=0,
        suggested_confidence=0.0,
        candidate_matches=[],
        review_fields=[],
        recovered_fields=[],
        recovery_candidates=[],
        blocking_reasons=[],
        quick_fix_actions=[],
        bulk_fix_groups=[],
        immutable_conflict=False,
        recoverability_class="review_recoverable",
        issue_group="other",
        issue_title="Needs attention",
        issue_summary="This line needs a quick review before we continue.",
        metadata={"row": 99, "entity_type": "listing", "safe": "kept", "source_header": "Budget"},
    )

    row = build_compatibility_review_row(item)

    assert row["row"] == 3
    assert row["entity_type"] == "client"
    assert row["issue_group"] == "other"
    assert "safe" not in row
    assert "source_header" not in row
    assert row["metadata"] == {"safe": "kept", "source_header": "Budget"}


def test_review_issue_classification_prefers_structured_signals_over_text() -> None:
    assert (
        classify_review_issue({"remarks": ["duplicate word only"], "candidate_matches": []})[0]
        == "other"
    )
    assert (
        classify_review_issue({"remarks": ["property area is 90m2"], "review_fields": []})[0]
        == "other"
    )


def test_phone_conflict_exposes_match_multiplicity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        def __enter__(self) -> _FakeSession:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def execute(self, *_args: object, **_kwargs: object) -> _FakeSession:
            return self

        def fetchall(self) -> list[dict[str, object]]:
            return [
                {"id": 10, "family_name": "A", "phone": "0555001001"},
                {"id": 11, "family_name": "B", "phone": "0555001001"},
            ]

    class _FakeUow:
        def session(self, *, actor: str) -> _FakeSession:
            return _FakeSession()

    monkeypatch.setattr("server.services.import_review_phone_conflicts.get_uow", lambda: _FakeUow())

    conflicts = detect_create_conflicts(
        entity_type="client",
        agency_id=12,
        pending_rows=[
            {
                "row_num": 1,
                "entity_type": "client",
                "validated_row": {"phone": "0555001001"},
                "correction_payload": {},
                "review_entry": {},
            }
        ],
    )

    assert conflicts[0]["existing_id"] == 10
    assert conflicts[0]["match_count"] == 2
    assert conflicts[0]["has_more_matches"] is True
    assert [candidate["id"] for candidate in conflicts[0]["candidate_summaries"]] == [10, 11]
    assert (
        classify_review_issue(
            {
                "candidate_matches": [{"id": 1}],
                "review_fields": [{"field": "wilaya"}],
                "remarks": ["missing location"],
            }
        )[0]
        == "possible_duplicate"
    )


def test_review_bulk_fix_groups_are_computed_over_full_review_set() -> None:
    job = SimpleNamespace(
        id="job-bulk",
        inference_summary={"final_inference": {"bundle_mode": "single_entity"}},
    )
    rows = [
        {
            "row": 1,
            "entity_type": "client",
            "raw_data": {"wilaya": "Alger"},
            "normalized_data": {},
            "recovery_candidates": [
                {"field": "wilaya", "candidate_label": "Alger", "candidate_value": "16"}
            ],
        },
        {
            "row": 50,
            "entity_type": "client",
            "raw_data": {"wilaya": "Alger"},
            "normalized_data": {},
            "recovery_candidates": [
                {"field": "wilaya", "candidate_label": "Alger", "candidate_value": "16"}
            ],
        },
    ]

    groups_by_key, _group_meta, _visible_count, _issue_counts, _conflict_count = (
        _grouped_review_state(job, rows)
    )

    grouped_rows = [row for group_rows in groups_by_key.values() for row in group_rows]
    rows_by_num = {int(row["row"]): row for row in grouped_rows}
    assert rows_by_num[1]["bulk_fix_groups"][0]["target_rows"] == [1, 50]
    assert rows_by_num[50]["bulk_fix_groups"][0]["occurrence_count"] == 2


def test_import_endgame_source_guards() -> None:
    services_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("server/services").glob("*.py")
        if path.name != "import_location_normalizer.py"
    )
    workflow_storage = Path("server/services/import_workflow_storage.py").read_text(
        encoding="utf-8"
    )
    review_queries = Path("server/services/import_review_queries.py").read_text(encoding="utf-8")
    review_compatibility = Path("server/services/import_review_compatibility.py").read_text(
        encoding="utf-8"
    )
    workflow_dispatch = Path("server/services/import_workflow_dispatch.py").read_text(
        encoding="utf-8"
    )
    work_admission_source = Path("server/services/work_admission.py").read_text(encoding="utf-8")
    phase_task_source = Path("server/api/tasks_import_phase_tasks.py").read_text(encoding="utf-8")
    distributed_plan_source = Path("server/services/import_distributed_plan_phase.py").read_text(
        encoding="utf-8"
    )
    artifact_checkpoint_source = Path("server/services/import_artifact_checkpoint.py").read_text(
        encoding="utf-8"
    )

    assert "_LOCATION_NORMALIZER" not in services_text
    assert "started_monotonic" not in workflow_storage
    assert "normalized_item.update(dict(metadata_payload))" not in review_queries
    assert "compatibility_row.update(metadata)" not in review_compatibility
    assert "error_rows += review_overflow_total" not in workflow_dispatch
    assert 'counts["degraded"] = 1' in work_admission_source
    assert "with ReviewRowBuffer() as review_rows" in phase_task_source
    assert "review_rows.cleanup()" in distributed_plan_source
    assert "restored_review_rows.cleanup()" in artifact_checkpoint_source
