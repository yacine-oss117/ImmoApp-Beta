"""Import-related Celery task entrypoints."""

from __future__ import annotations

from typing import Any

from server.services.import_chunk_workflow import advance_workflow
from server.services.import_notifications import emit_import_notification
from server.services.storage import download_to_temp

from .tasks_core import enqueue_import_task, task_decorator
from .tasks_import_execute import run_import_execute_task
from .tasks_import_parse import run_import_parse_task
from .tasks_import_phase_tasks import (
    run_import_finalize_job_task,
    run_import_load_chunk_task,
    run_import_plan_chunk_task,
    run_import_prepare_phase_task,
)


def _enqueue_prepare_phase_task(
    *,
    session_id: str,
    user_id: int,
    agency_id: int,
    schema: str | None,
    correlation_id: str | None,
) -> None:
    enqueue_import_task(
        import_prepare_phase_task,
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        schema=schema,
        correlation_id=correlation_id,
    )


def _queue_import_dispatch(
    *,
    session_id: str,
    user_id: int,
    agency_id: int,
    schema: str | None,
    correlation_id: str | None,
) -> None:
    dispatch = advance_workflow(session_id)
    for phase_id in dispatch.plan_phase_ids:
        enqueue_import_task(
            import_plan_chunk_task,
            session_id=session_id,
            user_id=user_id,
            agency_id=agency_id,
            phase_id=phase_id,
            schema=schema,
            correlation_id=correlation_id,
        )
    for phase_id in dispatch.load_phase_ids:
        enqueue_import_task(
            import_load_chunk_task,
            session_id=session_id,
            user_id=user_id,
            agency_id=agency_id,
            phase_id=phase_id,
            schema=schema,
            correlation_id=correlation_id,
        )
    if dispatch.finalize_job:
        enqueue_import_task(
            import_finalize_job_task,
            session_id=session_id,
            user_id=user_id,
            agency_id=agency_id,
            schema=schema,
            correlation_id=correlation_id,
        )


@task_decorator()
def import_parse_task(
    _task: object,
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    return run_import_parse_task(
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        schema=schema,
        correlation_id=correlation_id,
    )


@task_decorator()
def import_execute_task(
    _task: object,
    _call_marker: object | None = None,
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    entity_type: str,
    column_mapping: dict[str, str],
    skip_rows: int = 0,
    duplicate_strategy: str = "skip",
    skip_review_rows: bool = False,
    corrections: dict[str, dict[str, Any]] | None = None,
    execution_cost: int = 1,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return run_import_execute_task(
        _task=_task,
        _call_marker=_call_marker,
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        entity_type=entity_type,
        column_mapping=column_mapping,
        skip_rows=skip_rows,
        duplicate_strategy=duplicate_strategy,
        skip_review_rows=skip_review_rows,
        corrections=corrections,
        execution_cost=execution_cost,
        schema=schema,
        correlation_id=correlation_id,
        queue_import_dispatch_fn=_queue_import_dispatch,
        enqueue_prepare_phase_task_fn=_enqueue_prepare_phase_task,
        emit_import_notification_fn=emit_import_notification,
    )


@task_decorator(autoretry_for=())
def import_prepare_phase_task(
    _task: object,
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return run_import_prepare_phase_task(
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        schema=schema,
        correlation_id=correlation_id,
        queue_import_dispatch_fn=_queue_import_dispatch,
        download_to_temp_fn=download_to_temp,
    )


@task_decorator()
def import_plan_chunk_task(
    _task: object,
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    phase_id: int,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return run_import_plan_chunk_task(
        _task=_task,
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        phase_id=phase_id,
        schema=schema,
        correlation_id=correlation_id,
        queue_import_dispatch_fn=_queue_import_dispatch,
    )


@task_decorator()
def import_load_chunk_task(
    _task: object,
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    phase_id: int,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return run_import_load_chunk_task(
        _task=_task,
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        phase_id=phase_id,
        schema=schema,
        correlation_id=correlation_id,
        queue_import_dispatch_fn=_queue_import_dispatch,
    )


@task_decorator(autoretry_for=())
def import_finalize_job_task(
    _task: object,
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return run_import_finalize_job_task(
        _task=_task,
        session_id=session_id,
        user_id=user_id,
        agency_id=agency_id,
        schema=schema,
        correlation_id=correlation_id,
    )


__all__ = [
    "import_parse_task",
    "import_execute_task",
]
