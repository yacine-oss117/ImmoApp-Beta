"""Post-commit rebuild handoff owners for importer writes and review corrections."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from server.async_task_identity import build_context_async_task_identity
from server.services.import_constants import (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
    normalize_entity_type,
)
from server.services.import_follow_up import (
    persist_post_import_follow_up,
    run_post_import_follow_up,
)
from server.services.import_types import ImportLoadOutcome

logger = logging.getLogger(__name__)


class OnCommitRegistrar(Protocol):
    def on_commit(self, callback: Callable[[], None]) -> None: ...


def enqueue_post_import_rebuilds(
    *,
    entity_type: str,
    agency_id: int,
    listing_wilaya_ids: set[int],
    demande_ids: set[int],
    demande_client_ids: set[int],
    offer_ids: set[int],
) -> None:
    if entity_type == ENTITY_TYPE_CLIENT:
        from server.api.tasks import rebuild_match_cache_dirty

        task_identity = build_context_async_task_identity(agency_id=agency_id)
        if task_identity is None:
            logger.warning(
                "Skipping importer match-cache rebuild handoff: missing async tenant identity"
            )
            return
        rebuild_match_cache_dirty.delay(**task_identity)
        return

    if entity_type == ENTITY_TYPE_LISTING and listing_wilaya_ids:
        from server.services.match_jobs import enqueue_rebuild_wilaya_pairs

        for wilaya_id in sorted(listing_wilaya_ids):
            enqueue_rebuild_wilaya_pairs(wilaya_id)
        return

    if entity_type == ENTITY_TYPE_DEMANDE and demande_ids:
        from server.services.match_jobs import enqueue_rebuild_demande_pairs_batch

        enqueue_rebuild_demande_pairs_batch(sorted(demande_ids), agency_id=agency_id)
        return

    if entity_type == ENTITY_TYPE_DEMANDE and demande_client_ids:
        from server.services.match_jobs import enqueue_rebuild_client_pairs

        for client_id in sorted(demande_client_ids):
            enqueue_rebuild_client_pairs(client_id)
        return

    if entity_type == ENTITY_TYPE_OFFER and offer_ids:
        from server.services.match_jobs import (
            enqueue_rebuild_offer_pairs_batch,
            enqueue_rebuild_wilaya_pairs,
        )

        if listing_wilaya_ids:
            for wilaya_id in sorted(listing_wilaya_ids):
                enqueue_rebuild_wilaya_pairs(wilaya_id)
            return
        enqueue_rebuild_offer_pairs_batch(sorted(offer_ids), agency_id=agency_id)


def enqueue_post_import_rebuilds_for_entities(
    *,
    entity_types: set[str],
    agency_id: int,
    listing_wilaya_ids: set[int],
    demande_ids: set[int],
    demande_client_ids: set[int],
    offer_ids: set[int],
) -> None:
    for entity_type in sorted({normalize_entity_type(value) for value in entity_types if value}):
        if entity_type == ENTITY_TYPE_OFFER and listing_wilaya_ids:
            continue
        enqueue_post_import_rebuilds(
            entity_type=entity_type,
            agency_id=agency_id,
            listing_wilaya_ids=listing_wilaya_ids,
            demande_ids=demande_ids,
            demande_client_ids=demande_client_ids,
            offer_ids=offer_ids,
        )


def schedule_single_entity_after_commit(
    *,
    write_session: OnCommitRegistrar,
    entity_type: str,
    job_id: str,
    agency_id: int,
    load_outcome: ImportLoadOutcome,
) -> None:
    resolved_entity_type = str(entity_type)
    resolved_agency_id = int(agency_id)
    post_commit_wilayas = set(load_outcome.listing_wilaya_ids)
    post_commit_demande_ids = set(load_outcome.demande_ids)
    post_commit_demande_client_ids = set(load_outcome.demande_client_ids)
    post_commit_offer_ids = set(load_outcome.offer_ids)

    def _after_commit() -> None:
        try:
            outcome = run_post_import_follow_up(
                job_id=job_id,
                entity_types={resolved_entity_type},
                rebuild_handoff=lambda: enqueue_post_import_rebuilds(
                    entity_type=resolved_entity_type,
                    agency_id=resolved_agency_id,
                    listing_wilaya_ids=post_commit_wilayas,
                    demande_ids=post_commit_demande_ids,
                    demande_client_ids=post_commit_demande_client_ids,
                    offer_ids=post_commit_offer_ids,
                ),
            )
            persist_post_import_follow_up(job_id=job_id, outcome=outcome)
        except Exception:
            logger.warning(
                "Import committed but post-commit follow-up wrapper failed for job %s",
                job_id,
                exc_info=True,
            )

    write_session.on_commit(_after_commit)


def schedule_bundle_after_commit(
    *,
    write_session: OnCommitRegistrar,
    job_id: str,
    agency_id: int,
    load_outcome: ImportLoadOutcome,
) -> None:
    resolved_agency_id = int(agency_id)
    post_commit_wilayas = set(load_outcome.listing_wilaya_ids)
    post_commit_demande_ids = set(load_outcome.demande_ids)
    post_commit_demande_client_ids = set(load_outcome.demande_client_ids)
    post_commit_offer_ids = set(load_outcome.offer_ids)
    committed_entities = set(load_outcome.committed_entities)

    def _after_commit() -> None:
        try:
            outcome = run_post_import_follow_up(
                job_id=job_id,
                entity_types=committed_entities,
                rebuild_handoff=lambda: enqueue_post_import_rebuilds_for_entities(
                    entity_types=committed_entities,
                    agency_id=resolved_agency_id,
                    listing_wilaya_ids=post_commit_wilayas,
                    demande_ids=post_commit_demande_ids,
                    demande_client_ids=post_commit_demande_client_ids,
                    offer_ids=post_commit_offer_ids,
                ),
            )
            persist_post_import_follow_up(job_id=job_id, outcome=outcome)
        except Exception:
            logger.warning(
                "Import committed but post-commit follow-up wrapper failed for job %s",
                job_id,
                exc_info=True,
            )

    write_session.on_commit(_after_commit)


def schedule_review_corrections_after_commit(
    *,
    write_session: OnCommitRegistrar,
    entity_type: str,
    job_id: str,
    agency_id: int,
    load_outcome: ImportLoadOutcome,
) -> None:
    resolved_entity_type = str(entity_type)
    resolved_agency_id = int(agency_id)
    post_commit_wilayas = set(load_outcome.listing_wilaya_ids)
    post_commit_demande_ids = set(load_outcome.demande_ids)
    post_commit_demande_client_ids = set(load_outcome.demande_client_ids)
    post_commit_offer_ids = set(load_outcome.offer_ids)

    def _after_commit() -> None:
        try:
            outcome = run_post_import_follow_up(
                job_id=job_id,
                entity_types={resolved_entity_type},
                rebuild_handoff=lambda: enqueue_post_import_rebuilds(
                    entity_type=resolved_entity_type,
                    agency_id=resolved_agency_id,
                    listing_wilaya_ids=post_commit_wilayas,
                    demande_ids=post_commit_demande_ids,
                    demande_client_ids=post_commit_demande_client_ids,
                    offer_ids=post_commit_offer_ids,
                ),
            )
            persist_post_import_follow_up(job_id=job_id, outcome=outcome)
        except Exception:
            logger.warning(
                "Review corrections committed but post-commit follow-up wrapper failed for job %s",
                job_id,
                exc_info=True,
            )

    write_session.on_commit(_after_commit)


__all__ = [
    "OnCommitRegistrar",
    "enqueue_post_import_rebuilds",
    "enqueue_post_import_rebuilds_for_entities",
    "schedule_bundle_after_commit",
    "schedule_review_corrections_after_commit",
    "schedule_single_entity_after_commit",
]
