"""
Import service layer with permission checks and business logic.

This service layer:
- Validates user permissions (role + can_import)
- Enforces multi-tenant isolation (agency_id from context)
- Provides atomic transaction support for imports
- Manages persistent ImportJob state
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from core.contracts.import_batch_refs import CreatedRowRef
from server.imports.models import ImportJob
from server.services import import_jobs
from server.services.import_executor import execute_import
from server.services.import_permissions import (
    ImportPermissionError,
    UserProtocol,
    validate_import_permissions,
)
from server.services.import_review_execution_service import (
    apply_review_resolutions,
    insert_review_corrections,
    submit_review,
)
from server.services.import_review_payloads import NormalizedReviewSubmitRequest
from server.services.import_rows import validate_row
from server.services.import_types import ImportResult, ReviewRowPayload


class ImportService:
    """Service layer for import operations.

    Handles:
    - Permission validation
    - ImportJob management (DB-backed)
    - Import execution with atomic transactions
    """

    def __init__(self, user: UserProtocol) -> None:
        """Initialize import service.

        Args:
            user: The authenticated user from request.

        Raises:
            ImportPermissionError: If user lacks permission.
        """
        self.user = user
        self.user_id = user.id
        self.agency_id = user.agency_id
        validate_import_permissions(self.user)

    def create_job(
        self,
        filename: str,
        file_type: str,
        headers: list[str],
        source_path: str,
    ) -> ImportJob:
        """Create a new import job in the database."""
        return import_jobs.create_job(
            self.user,
            agency_id=self.agency_id,
            filename=filename,
            file_type=file_type,
            headers=headers,
            source_path=source_path,
        )

    def get_job(self, job_id: str) -> ImportJob | None:
        """Fetch job by ID."""
        return import_jobs.get_job_scoped(
            job_id=job_id,
            user=self.user,
            agency_id=self.agency_id,
        )

    def get_job_by_task_id(self, task_id: str) -> ImportJob | None:
        """Find job by associated task ID."""
        return import_jobs.get_job_by_task_id(self.user, task_id)

    def update_job(self, job: ImportJob) -> None:
        """Persist job updates to DB."""
        import_jobs.update_job(job)

    def validate_row(
        self,
        row: dict[str, Any],
        entity_type: str,
    ) -> tuple[dict[str, Any], list[str]]:
        """Validate a single row using ImportValidator."""
        return validate_row(row, entity_type)

    def execute_import(
        self,
        job: ImportJob,
        skip_rows: int = 0,
        skip_review_rows: bool = False,
        duplicate_strategy: str = "skip",
        corrections: dict[str, dict[str, Any]] | None = None,
    ) -> ImportResult:
        """Execute the import with streaming rows and atomic transaction."""
        return execute_import(
            job=job,
            user_id=self.user_id,
            skip_rows=skip_rows,
            skip_review_rows=skip_review_rows,
            duplicate_strategy=duplicate_strategy,
            corrections=corrections,
        )

    def insert_review_corrections(
        self,
        *,
        job_id: str,
        entity_type: str,
        corrected_rows: list[dict[str, Any]],
    ) -> list[CreatedRowRef]:
        """Insert corrected review rows via service layer only."""
        return insert_review_corrections(
            job_id=job_id,
            entity_type=entity_type,
            corrected_rows=corrected_rows,
            user_id=self.user_id,
            agency_id=self.agency_id,
        )

    def apply_review_resolutions(
        self,
        *,
        job_id: str = "",
        entity_type: str,
        review_rows: list[ReviewRowPayload],
        corrections: Mapping[str, Mapping[str, object]] | None,
        decisions: Mapping[str, Mapping[str, object]] | None,
        skip_rows: list[int | str] | None,
    ) -> dict[str, object]:
        return apply_review_resolutions(
            job_id=job_id,
            entity_type=entity_type,
            review_rows=review_rows,
            corrections=corrections,
            decisions=decisions,
            skip_rows=skip_rows,
            user_id=self.user_id,
            agency_id=self.agency_id,
        )

    def submit_review(
        self,
        *,
        job: ImportJob,
        entity_type: str,
        request_payload: NormalizedReviewSubmitRequest,
        enqueue_review_submit_task_fn: Callable[..., Any],
        register_task_fn: Callable[..., object],
        schema: str | None,
        correlation_id: str | None,
    ) -> dict[str, object]:
        return submit_review(
            job=job,
            actor_user_id=self.user_id,
            agency_id=self.agency_id,
            entity_type=entity_type,
            request_payload=request_payload,
            enqueue_review_submit_task_fn=enqueue_review_submit_task_fn,
            register_task_fn=register_task_fn,
            schema=schema,
            correlation_id=correlation_id,
        )


def get_active_schema() -> str:
    """Return active DB schema for task payload propagation."""
    from server.pg.uow import get_current_schema

    return get_current_schema()


__all__ = ["ImportPermissionError", "ImportService", "get_active_schema"]
