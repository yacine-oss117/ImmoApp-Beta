"""
Auth security event service.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from core.data import auth_security_events as repo
from server.pg.uow import get_uow

logger = logging.getLogger(__name__)
_ALLOWED_OUTCOMES = {"attempt", "success", "failure", "unknown"}


def _normalize_outcome(outcome: str) -> str:
    normalized = str(outcome or "").strip().lower()
    return normalized if normalized in _ALLOWED_OUTCOMES else "unknown"


def log_auth_event(
    *,
    event_type: str,
    outcome: str,
    agency_id: int | None = None,
    user_id: int | None = None,
    identifier: str | None = None,
    reason_code: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    details: Mapping[str, Any] | None = None,
    fail_silently: bool = True,
) -> None:
    normalized_outcome = _normalize_outcome(outcome)
    try:
        with get_uow().transaction(is_superuser=True, actor="auth-security") as session:
            repo.insert_auth_event(
                session,
                event_type=event_type,
                outcome=normalized_outcome,
                agency_id=agency_id,
                user_id=user_id,
                identifier=identifier,
                reason_code=reason_code,
                source_ip=source_ip,
                user_agent=user_agent,
                request_id=request_id,
                details=details,
            )
    except Exception:
        if fail_silently:
            logger.warning("Failed to persist auth security event", exc_info=True)
            return
        raise


def fetch_auth_events(
    *,
    limit: int = 200,
    offset: int = 0,
    event_type: str | None = None,
    outcome: str | None = None,
    user_id: int | None = None,
    identifier: str | None = None,
    source_ip: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> list[dict[str, Any]]:
    with get_uow().session() as session:
        return repo.fetch_auth_events(
            session,
            limit=limit,
            offset=offset,
            event_type=event_type,
            outcome=outcome,
            user_id=user_id,
            identifier=identifier,
            source_ip=source_ip,
            start_ts=start_ts,
            end_ts=end_ts,
        )


def count_auth_events(
    *,
    event_type: str | None = None,
    outcome: str | None = None,
    user_id: int | None = None,
    identifier: str | None = None,
    source_ip: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> int:
    with get_uow().session() as session:
        return repo.count_auth_events(
            session,
            event_type=event_type,
            outcome=outcome,
            user_id=user_id,
            identifier=identifier,
            source_ip=source_ip,
            start_ts=start_ts,
            end_ts=end_ts,
        )


def purge_old_auth_events(*, retention_days: int = 90) -> int:
    with get_uow().transaction(is_superuser=True, actor="auth-security-purge") as session:
        return repo.purge_old_auth_events(session, retention_days)


__all__ = [
    "count_auth_events",
    "fetch_auth_events",
    "log_auth_event",
    "purge_old_auth_events",
]
