"""Async review-submit task entrypoints."""

from __future__ import annotations

from server.services.import_review_submit_service import run_review_submit_task

from .tasks_core import require_agency_id, task_context, task_decorator
from .tasks_import_helpers import load_import_user


@task_decorator(autoretry_for=())
def import_review_submit_task(
    _task: object,
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    agency_id = require_agency_id(agency_id, "import_review_submit_task")
    user = load_import_user(user_id)
    with task_context(
        schema,
        agency_id,
        actor_id=getattr(user, "id", None) if user else None,
        actor_role=str(getattr(user, "role", "") or None) if user else None,
        actor_is_owner=bool(getattr(user, "is_owner", False)) if user else False,
        correlation_id=correlation_id,
    ):
        return run_review_submit_task(
            session_id=session_id,
            actor_user_id=user_id,
            agency_id=agency_id,
            correlation_id=correlation_id,
            task_id=str(getattr(getattr(_task, "request", None), "id", "") or ""),
        )


__all__ = ["import_review_submit_task"]
