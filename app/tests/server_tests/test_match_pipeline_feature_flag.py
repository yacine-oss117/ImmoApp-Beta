from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

pytest.importorskip(
    "cryptography", reason="match pipeline feature-flag tests require server dependencies"
)


def test_compute_match_artifacts_uses_direct_pipeline_when_flag_enabled(monkeypatch) -> None:
    from server.api import match_pairs_compute

    direct_calls: list[list[int]] = []
    legacy_calls: list[list[int]] = []

    monkeypatch.setenv("IMMOAPP_MATCH_BUILD_PIPELINE", "direct")
    monkeypatch.setattr(
        match_pairs_compute,
        "business_span",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(set_attribute=lambda *a, **k: None)),
    )
    monkeypatch.setattr(
        match_pairs_compute.match_artifact_pipeline,
        "rebuild_match_artifacts_for_demandes",
        lambda _session, demande_ids, *, limit: direct_calls.append(list(demande_ids))
        or match_pairs_compute.match_artifact_pipeline.MatchArtifactBatchResult(
            candidate_total=2,
            ranked_total=2,
            pair_total=1,
            per_demande={
                11: match_pairs_compute.match_artifact_pipeline.MatchArtifactCounts(
                    candidate_total=2,
                    ranked_total=2,
                    pair_total=1,
                )
            },
        ),
    )
    monkeypatch.setattr(
        match_pairs_compute.match_candidates_data,
        "replace_candidates_for_demandes_from_match_query",
        lambda _session, demande_ids: legacy_calls.append(list(demande_ids)) or {},
    )
    monkeypatch.setattr(
        match_pairs_compute.match_pairs_data,
        "rebuild_pairs_for_demandes_from_candidates_sql",
        lambda _session, demande_ids, *, limit: legacy_calls.append(list(demande_ids))
        or (0, 0, {}),
    )
    monkeypatch.setattr(
        match_pairs_compute,
        "record_match_artifact_pipeline",
        lambda **kwargs: None,
    )

    result = match_pairs_compute.compute_match_artifacts_for_demandes(
        object(),
        [11],
        limit=1,
    )

    assert direct_calls == [[11]]
    assert legacy_calls == []
    assert result.candidate_total == 2
    assert result.pair_total == 1


def test_compute_match_artifacts_uses_legacy_pipeline_when_flag_disabled(monkeypatch) -> None:
    from server.api import match_pairs_compute

    monkeypatch.setenv("IMMOAPP_MATCH_BUILD_PIPELINE", "legacy")
    monkeypatch.setattr(
        match_pairs_compute,
        "business_span",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(set_attribute=lambda *a, **k: None)),
    )
    monkeypatch.setattr(
        match_pairs_compute,
        "record_match_artifact_pipeline",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        match_pairs_compute.match_candidates_data,
        "replace_candidates_for_demandes_from_match_query",
        lambda _session, demande_ids: {11: 2},
    )
    monkeypatch.setattr(
        match_pairs_compute.match_pairs_data,
        "rebuild_pairs_for_demandes_from_candidates_sql",
        lambda _session, demande_ids, *, limit: (1, 2, {11: (1, 2)}),
    )

    result = match_pairs_compute.compute_match_artifacts_for_demandes(
        object(),
        [11],
        limit=1,
    )

    assert result.candidate_total == 2
    assert result.ranked_total == 2
    assert result.pair_total == 1
    assert result.per_demande[11].pair_total == 1


def test_compute_match_artifacts_defaults_to_direct_pipeline(monkeypatch) -> None:
    from server.api import match_pairs_compute

    monkeypatch.delenv("IMMOAPP_MATCH_BUILD_PIPELINE", raising=False)
    assert match_pairs_compute._match_build_pipeline_mode() == "direct"
