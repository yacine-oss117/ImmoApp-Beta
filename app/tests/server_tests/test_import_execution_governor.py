from __future__ import annotations

from server.services import import_execution_governor


def test_import_execution_cost_model_scales_with_rows_and_review_mode() -> None:
    assert (
        import_execution_governor.calculate_import_execution_cost(
            rows=500,
            entity_type="client",
            duplicate_strategy="review",
        )
        == 1
    )
    assert (
        import_execution_governor.calculate_import_execution_cost(
            rows=3500,
            entity_type="client",
            duplicate_strategy="review",
        )
        == 5
    )
    assert (
        import_execution_governor.calculate_import_execution_cost(
            rows=100,
            entity_type="offer",
            duplicate_strategy="allow_all",
        )
        == 1
    )
    assert (
        import_execution_governor.calculate_import_execution_cost(
            rows=2500,
            entity_type="offer",
            duplicate_strategy="review",
            bundle_mode="same_side_bundle",
            expected_review_ratio=0.35,
        )
        == 8
    )


def test_profile_aware_chunk_ceiling_respects_runtime_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        import_execution_governor,
        "effective_import_runtime_profile",
        lambda: import_execution_governor.ImportExecutionProfile(
            name="red",
            chunk_rows=100,
            duplicate_candidates=2,
            worker_concurrency_hint=1,
        ),
    )

    assert import_execution_governor.profile_aware_chunk_ceiling(500) == 100
    assert import_execution_governor.profile_aware_chunk_ceiling(50) == 50
