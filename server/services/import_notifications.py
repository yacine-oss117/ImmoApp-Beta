"""Centralized importer notifications."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

from server.api.notifications import notify_only, record_and_notify, record_and_notify_in_atomic
from server.services.json_safe import json_safe_value


class ImportSuccessNotificationOutcome(TypedDict):
    state: Literal["completed"]
    reason_code: str
    recovery_owner: str


def emit_import_notification(
    *,
    event_type: str,
    user_id: int,
    title: str,
    body: str,
    agency_id: int | None = None,
    data: Mapping[str, object] | None = None,
    persist: bool = True,
) -> None:
    safe_payload = json_safe_value(dict(data or {}))
    payload = dict(safe_payload) if isinstance(safe_payload, dict) else {}
    if persist:
        record_and_notify(
            agency_id=agency_id,
            scope="user",
            user_id=user_id,
            event_type=event_type,
            title=title,
            body=body,
            data=payload,
        )
        return
    notify_only(
        scope="user",
        user_id=user_id,
        event_type=event_type,
        title=title,
        body=body,
        data=payload,
    )


def record_import_success_notification(
    *,
    agency_id: int,
    user_id: int,
    job_id: str,
    filename: str,
    entity_type: str,
    created_count: int,
    updated_count: int,
    error_count: int,
    review_total_count: int,
    review_overflow_count: int,
    review_pending_group_count: int,
) -> ImportSuccessNotificationOutcome:
    record_and_notify_in_atomic(
        agency_id=int(agency_id),
        scope="user",
        user_id=user_id,
        event_type="import.execution_completed",
        title="Import finished",
        body=f"Your import for {filename} completed successfully.",
        data={
            "session_id": str(job_id),
            "entity_type": str(entity_type or ""),
            "created": int(created_count or 0),
            "updated": int(updated_count or 0),
            "errors": int(error_count or 0),
            "review": int(review_total_count or 0),
            "review_overflow_count": int(review_overflow_count or 0),
            "review_pending_group_count": int(review_pending_group_count or 0),
        },
    )
    return {
        "state": "completed",
        "reason_code": "",
        "recovery_owner": "",
    }


__all__ = ["emit_import_notification", "record_import_success_notification"]
