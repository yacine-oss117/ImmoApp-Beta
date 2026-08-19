"""
Persist Celery task failures for post-mortem analysis.
"""

from __future__ import annotations

import logging
from typing import Any

from .uow import admin_transaction

logger = logging.getLogger(__name__)


def _agency_exists(session: Any, agency_id: int) -> bool:
    row = session.execute(
        """
        SELECT EXISTS(
            SELECT 1
            FROM public.accounts_agency
            WHERE id = %s
        ) AS agency_exists
        """,
        (int(agency_id),),
    ).fetchone()
    return bool((row or {}).get("agency_exists"))


def record_task_failure(
    *,
    task_id: str | None,
    name: str | None,
    args: Any,
    kwargs: Any,
    exception: Exception | None,
    traceback_text: str | None,
    schema_name: str | None,
    agency_id: int | None,
) -> None:
    """Store task failure details in the database (best-effort).

    Uses admin_transaction but sets app.current_agency_id so the DB DEFAULT
    can populate agency_id. If agency_id is None, the column remains NULL
    (allowed for task_failures table).
    """
    try:
        args_text = _safe_str(args)
        kwargs_text = _safe_str(kwargs)
        exc_text = _safe_str(exception)
        trace_text = _safe_str(traceback_text)
        with admin_transaction(schema=schema_name) as session:
            # Set tenant context so DB DEFAULT can fill agency_id
            if agency_id is not None and _agency_exists(session, int(agency_id)):
                session.execute(
                    "SELECT set_config('app.current_agency_id', %s, true)",
                    (str(agency_id),),
                )
            # Omit agency_id from INSERT - DB DEFAULT fills it from context
            session.execute(
                """
                INSERT INTO task_failures
                    (task_id, name, args, kwargs, exception, traceback, schema_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task_id or "",
                    name or "",
                    args_text,
                    kwargs_text,
                    exc_text,
                    trace_text,
                    schema_name or "",
                ),
            )
    except Exception:
        logger.warning("Failed to persist task failure", exc_info=True)


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return "<unserializable>"
