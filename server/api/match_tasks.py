"""
Celery tasks for match processing using Celery/RabbitMQ instead of custom async worker.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from core.matcher.batch_match_processor import BatchOperationType
from server.api.tasks_core import task_decorator

logger = logging.getLogger(__name__)


@task_decorator(max_retries=3)
def count_matches_for_clients_task(
    self: Any, client_ids: list[int], agency_id: int | None = None
) -> dict[int, int]:
    """
    Celery task to count matches for multiple clients.
    """
    try:
        logger.info(f"Starting match count for {len(client_ids)} clients")

        # Use synchronous match counter with UoW
        from core.matcher.match_counter import batch_count_clients_paginated
        from server.pg.uow import get_uow, use_security_context

        # Set security context if agency_id is provided
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session() as session:
                results = batch_count_clients_paginated(session, client_ids)

        logger.info(f"Completed match count for {len(client_ids)} clients")
        return results

    except Exception as exc:
        logger.error(f"Error in count_matches_for_clients_task: {exc}")
        raise


@task_decorator(max_retries=3)
def count_matches_for_demandes_task(
    self: Any, demande_ids: list[int], agency_id: int | None = None
) -> dict[int, int]:
    """
    Celery task to count matches for multiple demandes.
    """
    try:
        logger.info(f"Starting match count for {len(demande_ids)} demandes")

        from core.matcher.match_counter import count_demandes_by_ids
        from server.pg.uow import get_uow, use_security_context

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session() as session:
                results = count_demandes_by_ids(session, demande_ids)

        logger.info(f"Completed match count for {len(demande_ids)} demandes")
        return results

    except Exception as exc:
        logger.error(f"Error in count_matches_for_demandes_task: {exc}")
        raise


@task_decorator(max_retries=3)
def count_matches_for_listings_task(
    self: Any, listing_ids: list[int], agency_id: int | None = None
) -> dict[int, int]:
    """
    Celery task to count matches for multiple listings.
    """
    try:
        logger.info(f"Starting match count for {len(listing_ids)} listings")

        from core.matcher.match_counter import batch_count_listings_paginated
        from server.pg.uow import get_uow, use_security_context

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session() as session:
                results = batch_count_listings_paginated(session, listing_ids)

        logger.info(f"Completed match count for {len(listing_ids)} listings")
        return results

    except Exception as exc:
        logger.error(f"Error in count_matches_for_listings_task: {exc}")
        raise


@task_decorator(max_retries=3)
def count_matches_for_offers_task(
    self: Any, offer_ids: list[int], agency_id: int | None = None
) -> dict[int, int]:
    """
    Celery task to count matches for multiple offers.
    """
    try:
        logger.info(f"Starting match count for {len(offer_ids)} offers")

        from core.matcher.match_counter import count_offers_by_ids
        from server.pg.uow import get_uow, use_security_context

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session() as session:
                results = count_offers_by_ids(session, offer_ids)

        logger.info(f"Completed match count for {len(offer_ids)} offers")
        return results

    except Exception as exc:
        logger.error(f"Error in count_matches_for_offers_task: {exc}")
        raise


@shared_task(bind=True)
def batch_match_operation_task(
    self: Any,
    operation_type: str,
    entity_ids: list[int],
    agency_id: int | None = None,
    chunk_size: int = 50,
) -> dict[str, int]:
    """
    Generic batch match operation task.
    """
    try:
        logger.info(f"Starting batch operation {operation_type} for {len(entity_ids)} entities")

        from core.matcher.match_counter import (
            batch_count_clients_paginated,
            batch_count_listings_paginated,
            count_demandes_by_ids,
            count_offers_by_ids,
        )
        from server.pg.uow import get_uow, use_security_context

        total_processed = 0
        results = {}

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session() as session:
                # Process in chunks
                for i in range(0, len(entity_ids), chunk_size):
                    chunk = entity_ids[i : i + chunk_size]
                    chunk_results = {}

                    if operation_type == BatchOperationType.CLIENT_COUNTS.value:
                        chunk_results = batch_count_clients_paginated(session, chunk)
                    elif operation_type == BatchOperationType.DEMANDE_COUNTS.value:
                        chunk_results = count_demandes_by_ids(session, chunk)
                    elif operation_type == BatchOperationType.LISTING_COUNTS.value:
                        chunk_results = batch_count_listings_paginated(session, chunk)
                    elif operation_type == BatchOperationType.OFFER_COUNTS.value:
                        chunk_results = count_offers_by_ids(session, chunk)
                    else:
                        raise ValueError(f"Unknown operation type: {operation_type}")

                    results.update(chunk_results)
                    total_processed += len(chunk)

                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "current": total_processed,
                            "total": len(entity_ids),
                            "status": f"Processed {total_processed} of {len(entity_ids)} entities",
                        },
                    )

        logger.info(f"Completed batch operation {operation_type} for {len(entity_ids)} entities")
        return {"processed_count": total_processed, "results_count": len(results), "success": True}

    except Exception as exc:
        logger.error(f"Error in batch_match_operation_task: {exc}")
        raise


@shared_task(bind=True)
def clear_match_cache_task(self: Any) -> dict[str, bool]:
    """
    Task to clear the entire match cache.
    """
    try:
        logger.info("Starting match cache clear operation")

        from core.data import match_cache as match_cache_data
        from server.pg.uow import get_uow

        with get_uow().transaction() as session:
            match_cache_data.clear_all(session)

        logger.info("Completed match cache clear operation")
        return {"cache_cleared": True, "success": True}

    except Exception as exc:
        logger.error(f"Error in clear_match_cache_task: {exc}")
        raise
