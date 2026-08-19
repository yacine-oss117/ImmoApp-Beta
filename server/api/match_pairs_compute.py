"""Match pair computation helpers."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence

import psycopg

from core.data import demande_repository as demande_data
from core.data import lookup_tables, match_artifact_pipeline
from core.data import match_candidates as match_candidates_data
from core.data import match_pairs as match_pairs_data
from core.matcher.ports.db import DbSession
from server.immoapp_server.business_metrics_match import (
    record_match_artifact_pipeline,
    record_match_artifact_timeout,
    record_match_pair_rebuild,
)
from server.immoapp_server.observability import business_span

DEFAULT_MATCH_PAIRS_LIMIT = 100


def _match_build_pipeline_mode() -> str:
    raw = os.environ.get("IMMOAPP_MATCH_BUILD_PIPELINE", "direct").strip().lower()
    return "direct" if raw == "direct" else "legacy"


def _timeout_kind(exc: psycopg.Error) -> str | None:
    sqlstate = str(getattr(exc, "sqlstate", "") or "")
    message = str(exc).lower()
    if sqlstate == "55P03" or "lock timeout" in message:
        return "lock_timeout"
    if sqlstate == "57014" or "statement timeout" in message:
        return "statement_timeout"
    return None


def compute_match_artifacts_for_demandes(
    session: DbSession,
    demande_ids: Sequence[int],
    *,
    limit: int | None,
) -> match_artifact_pipeline.MatchArtifactBatchResult:
    normalized_ids = [int(v) for v in demande_ids if int(v) > 0]
    if not normalized_ids:
        return match_artifact_pipeline.MatchArtifactBatchResult(
            candidate_total=0,
            ranked_total=0,
            pair_total=0,
            per_demande={},
        )

    mode = _match_build_pipeline_mode()
    started_at = time.monotonic()
    with business_span(
        "matcher.compute_artifacts_for_demandes",
        attributes={
            "match.demande_batch_size": len(normalized_ids),
            "match.limit": limit,
            "match.pipeline_mode": mode,
        },
    ) as span:
        try:
            if mode == "direct":
                result = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    normalized_ids,
                    limit=limit,
                )
            else:
                candidate_counts = (
                    match_candidates_data.replace_candidates_for_demandes_from_match_query(
                        session,
                        normalized_ids,
                    )
                )
                stored_total, ranked_total, per_demande_pairs = (
                    match_pairs_data.rebuild_pairs_for_demandes_from_candidates_sql(
                        session,
                        normalized_ids,
                        limit=limit,
                    )
                )
                per_demande = {
                    demande_id: match_artifact_pipeline.MatchArtifactCounts(
                        candidate_total=int(candidate_counts.get(demande_id, 0)),
                        ranked_total=int(per_demande_pairs.get(demande_id, (0, 0))[1]),
                        pair_total=int(per_demande_pairs.get(demande_id, (0, 0))[0]),
                    )
                    for demande_id in normalized_ids
                }
                result = match_artifact_pipeline.MatchArtifactBatchResult(
                    candidate_total=sum(item.candidate_total for item in per_demande.values()),
                    ranked_total=int(ranked_total),
                    pair_total=int(stored_total),
                    per_demande=per_demande,
                )
        except psycopg.Error as exc:
            timeout_kind = _timeout_kind(exc)
            if timeout_kind:
                record_match_artifact_timeout(kind=timeout_kind)
                record_match_artifact_pipeline(
                    mode=mode,
                    outcome=timeout_kind,
                    batch_size=len(normalized_ids),
                    candidates=0,
                    ranked=0,
                    stored=0,
                    duration_s=max(0.0, time.monotonic() - started_at),
                )
                span.set_attribute(f"match.{timeout_kind}", True)
            raise

        span.set_attribute("match.candidates", result.candidate_total)
        span.set_attribute("match.pairs_ranked", result.ranked_total)
        span.set_attribute("match.pairs_stored", result.pair_total)
        span.set_attribute(
            "match.empty_demande_count",
            sum(1 for item in result.per_demande.values() if item.candidate_total <= 0),
        )
        record_match_artifact_pipeline(
            mode=mode,
            outcome="success" if result.candidate_total > 0 else "empty",
            batch_size=len(normalized_ids),
            candidates=result.candidate_total,
            ranked=result.ranked_total,
            stored=result.pair_total,
            duration_s=max(0.0, time.monotonic() - started_at),
        )
        return result


def compute_match_pairs_for_demande(
    session: DbSession,
    demande_id: int,
    *,
    limit: int | None,
) -> tuple[int, int]:
    started_at = time.monotonic()
    with business_span(
        "matcher.compute_pairs_for_demande",
        attributes={"match.demande_id": demande_id, "match.limit": limit},
    ) as span:
        demande = demande_data.get_demande_by_id(session, demande_id, include_deleted=False)
        if not demande:
            match_candidates_data.clear_candidates(session, demande_id=demande_id)
            match_pairs_data.clear_pairs(session, demande_id=demande_id)
            span.set_attribute("match.demande_exists", False)
            span.set_attribute("match.candidates", 0)
            span.set_attribute("match.pairs_stored", 0)
            record_match_pair_rebuild(
                outcome="missing_demande",
                candidates=0,
                stored=0,
                duration_s=max(0.0, time.monotonic() - started_at),
            )
            return 0, 0

        span.set_attribute("match.demande_exists", True)
        result = compute_match_artifacts_for_demandes(
            session,
            [demande.id],
            limit=limit,
        )
        counts = result.per_demande.get(
            int(demande.id),
            match_artifact_pipeline.MatchArtifactCounts(
                candidate_total=0,
                ranked_total=0,
                pair_total=0,
            ),
        )
        candidate_count = counts.candidate_total
        span.set_attribute("match.candidates", candidate_count)
        if candidate_count == 0:
            match_candidates_data.clear_candidates(session, demande_id=demande_id)
            match_pairs_data.clear_pairs(session, demande_id=demande_id)
            span.set_attribute("match.pairs_stored", 0)
            record_match_pair_rebuild(
                outcome="empty",
                candidates=0,
                stored=0,
                duration_s=max(0.0, time.monotonic() - started_at),
            )
            return 0, 0

        stored = counts.pair_total
        ranked = counts.ranked_total
        span.set_attribute("match.pairs_stored", stored)
        span.set_attribute("match.pairs_ranked", ranked)
        record_match_pair_rebuild(
            outcome="success",
            candidates=candidate_count,
            stored=stored,
            duration_s=max(0.0, time.monotonic() - started_at),
        )
        return stored, candidate_count


def compute_match_pairs_for_demandes(
    session: DbSession,
    demande_ids: Sequence[int],
    *,
    limit: int | None,
) -> tuple[int, int]:
    """Compute match pairs for multiple demandes with set-based SQL per batch."""
    normalized_ids = [int(v) for v in demande_ids if int(v) > 0]
    if not normalized_ids:
        return 0, 0

    started_at = time.monotonic()
    with business_span(
        "matcher.compute_pairs_for_demandes",
        attributes={
            "match.demande_batch_size": len(normalized_ids),
            "match.limit": limit,
        },
    ) as span:
        result = compute_match_artifacts_for_demandes(session, normalized_ids, limit=limit)
        candidate_total = result.candidate_total
        stored_total = result.pair_total
        span.set_attribute("match.candidates", candidate_total)
        span.set_attribute("match.pairs_ranked", result.ranked_total)
        span.set_attribute("match.pairs_stored", stored_total)
        record_match_pair_rebuild(
            outcome="success" if candidate_total > 0 else "empty",
            candidates=candidate_total,
            stored=stored_total,
            duration_s=max(0.0, time.monotonic() - started_at),
        )
        return stored_total, candidate_total


def resolve_wilaya_id(
    session: DbSession, wilaya_id: int | str | None, wilaya: str | None
) -> int | None:
    if isinstance(wilaya_id, int):
        return None if wilaya_id == 0 else wilaya_id
    if isinstance(wilaya_id, str):
        text = wilaya_id.strip()
        if text.isdigit():
            value = int(text)
            return None if value == 0 else value
        return lookup_tables.get_wilaya_id(session, text)
    if wilaya:
        return lookup_tables.get_wilaya_id(session, wilaya)
    return None


__all__ = [
    "DEFAULT_MATCH_PAIRS_LIMIT",
    "compute_match_artifacts_for_demandes",
    "compute_match_pairs_for_demande",
    "compute_match_pairs_for_demandes",
    "resolve_wilaya_id",
]
