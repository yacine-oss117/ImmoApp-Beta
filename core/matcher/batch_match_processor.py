"""
Batch processor for match computations using Celery for async processing.
This replaces the custom async worker with Celery/RabbitMQ-based processing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from core.data.types import ClientId, DemandeId, ListingId, OfferId
from server.api.match_tasks import batch_match_operation_task

logger = logging.getLogger(__name__)


class BatchOperationType(Enum):
    """Types of batch operations supported."""

    CLIENT_COUNTS = "CLIENT_COUNTS"
    DEMANDE_COUNTS = "DEMANDE_COUNTS"
    LISTING_COUNTS = "LISTING_COUNTS"
    OFFER_COUNTS = "OFFER_COUNTS"
    MATCH_UPDATES = "MATCH_UPDATES"


@dataclass
class BatchJob:
    """Represents a batch job for match computation."""

    job_id: str
    operation_type: BatchOperationType
    entity_ids: list[int]
    agency_id: int | None = None
    priority: int = 1  # Lower number means higher priority
    created_at: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    status: str = "pending"  # pending, running, completed, failed
    progress: float = 0.0  # 0.0 to 1.0
    result: dict[str, object] | None = None
    error: str | None = None


class BatchMatchProcessor:
    """
    Processor for batch match computations that uses Celery for async processing.
    """

    def __init__(self) -> None:
        # No need for internal workers since we're using Celery
        pass

    async def submit_job(self, job: BatchJob) -> str:
        """Submit a job to the Celery queue."""
        # Submit the task to Celery
        task = batch_match_operation_task.delay(
            operation_type=job.operation_type.value,
            entity_ids=job.entity_ids,
            agency_id=job.agency_id,
        )

        # Update job with Celery task ID
        job.job_id = str(task.id)
        job.status = "submitted"

        logger.info(
            f"Submitted job {task.id} for {job.operation_type.value} with {len(job.entity_ids)} entities"
        )
        return job.job_id

    async def get_job_status(self, job_id: str) -> BatchJob | None:
        """Get the status of a submitted job from Celery."""
        from celery.result import AsyncResult

        from server.immoapp_server.celery import celery_app

        result = AsyncResult(job_id, app=celery_app)

        # Map Celery states to our internal states
        status_map = {
            "PENDING": "pending",
            "STARTED": "running",
            "SUCCESS": "completed",
            "FAILURE": "failed",
            "RETRY": "running",
            "REVOKED": "failed",
        }

        status = status_map.get(result.state, "unknown")

        job = BatchJob(
            job_id=job_id,
            operation_type=BatchOperationType.CLIENT_COUNTS,  # Placeholder
            entity_ids=[],  # Not retrievable from Celery result
            status=status,
            result=result.result if result.ready() else None,
            error=str(result.info) if result.failed() else None,
        )

        return job


# Global instance
_batch_processor = BatchMatchProcessor()


async def get_batch_processor() -> BatchMatchProcessor:
    """Get the global batch processor instance."""
    return _batch_processor


async def submit_client_count_job(
    client_ids: list[ClientId], agency_id: int | None = None, priority: int = 1
) -> str:
    """Submit a Celery job to count matches for clients."""
    from server.api.match_tasks import count_matches_for_clients_task

    task = count_matches_for_clients_task.delay(client_ids=client_ids, agency_id=agency_id)
    return str(task.id)


async def submit_demande_count_job(
    demande_ids: list[DemandeId], agency_id: int | None = None, priority: int = 1
) -> str:
    """Submit a Celery job to count matches for demandes."""
    from server.api.match_tasks import count_matches_for_demandes_task

    task = count_matches_for_demandes_task.delay(demande_ids=demande_ids, agency_id=agency_id)
    return str(task.id)


async def submit_listing_count_job(
    listing_ids: list[ListingId], agency_id: int | None = None, priority: int = 1
) -> str:
    """Submit a Celery job to count matches for listings."""
    from server.api.match_tasks import count_matches_for_listings_task

    task = count_matches_for_listings_task.delay(listing_ids=listing_ids, agency_id=agency_id)
    return str(task.id)


async def submit_offer_count_job(
    offer_ids: list[OfferId], agency_id: int | None = None, priority: int = 1
) -> str:
    """Submit a Celery job to count matches for offers."""
    from server.api.match_tasks import count_matches_for_offers_task

    task = count_matches_for_offers_task.delay(offer_ids=offer_ids, agency_id=agency_id)
    return str(task.id)


async def get_job_status(job_id: str) -> dict[str, object]:
    """Get the status of a submitted Celery job."""
    from celery.result import AsyncResult

    from server.immoapp_server.celery import celery_app

    result = AsyncResult(job_id, app=celery_app)

    # Map Celery states to our internal states
    status_map = {
        "PENDING": "pending",
        "STARTED": "running",
        "SUCCESS": "completed",
        "FAILURE": "failed",
        "RETRY": "running",
        "REVOKED": "failed",
    }

    status = status_map.get(result.state, "unknown")

    return {
        "job_id": job_id,
        "status": status,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else False,
        "failed": result.failed() if result.ready() else False,
        "result": result.result if result.ready() else None,
        "traceback": result.traceback if result.failed() else None,
    }
