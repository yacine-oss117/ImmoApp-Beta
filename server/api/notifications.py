"""Notification utilities for WebSocket broadcast groups."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, TypedDict, cast
from uuid import uuid4

import psycopg
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import DatabaseError, transaction
from django.utils import timezone

from server.services.json_safe import json_safe_value
from server.services.notifications import insert_notification, insert_notification_in_atomic

NotificationPayload = dict[str, object]

GLOBAL_GROUP = "global"
logger = logging.getLogger(__name__)


class NotificationPersistenceError(RuntimeError):
    """Raised when the canonical notification record could not be persisted."""


class NotificationRecordResult(TypedDict):
    notification_id: int
    payload: NotificationPayload


def group_user(user_id: int) -> str:
    return f"user.{user_id}"


def group_agency(agency_id: int) -> str:
    return f"agency.{agency_id}"


def group_role(agency_id: int, role: str) -> str:
    return f"role.{agency_id}.{role}"


def group_owner(agency_id: int) -> str:
    return f"owner.{agency_id}"


def build_notification(
    *,
    event_type: str,
    title: str,
    body: str,
    scope: str,
    role: str | None = None,
    user_id: int | None = None,
    data: Mapping[str, object] | None = None,
) -> NotificationPayload:
    payload: NotificationPayload = {
        "id": str(uuid4()),
        "type": event_type,
        "title": title,
        "body": body,
        "scope": scope,
        "created_at": timezone.now().isoformat(),
    }
    if role is not None:
        payload["role"] = role
    if user_id is not None:
        payload["user_id"] = user_id
    if data:
        safe_data = json_safe_value(dict(data))
        payload["data"] = dict(safe_data) if isinstance(safe_data, dict) else {}
    return payload


def notify_group(group_name: str, payload: NotificationPayload) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    sender = cast(Any, channel_layer)
    async_to_sync(sender.group_send)(group_name, {"type": "notify", "payload": payload})


def broadcast_notification_payload(
    *,
    scope: str,
    payload: NotificationPayload,
    agency_id: int | None = None,
    role: str | None = None,
    user_id: int | None = None,
) -> None:
    from server.pg.uow import get_current_agency_id

    current_agency_id = (
        int(agency_id) if isinstance(agency_id, int) and agency_id > 0 else get_current_agency_id()
    )

    if scope == "user" and user_id is not None:
        notify_user(user_id, payload)
    elif scope == "role" and current_agency_id is not None and role:
        notify_role(current_agency_id, role, payload)
    elif scope == "owner" and current_agency_id is not None:
        notify_owner(current_agency_id, payload)
    elif scope == "agency" and current_agency_id is not None:
        notify_agency(current_agency_id, payload)
    elif scope == "global":
        notify_global(payload)
    else:
        notify_group(GLOBAL_GROUP, payload)


def record_notification(
    *,
    agency_id: int | None = None,
    scope: str,
    event_type: str,
    title: str,
    body: str,
    role: str | None = None,
    user_id: int | None = None,
    data: Mapping[str, object] | None = None,
    actor: str | None = None,
    is_superuser: bool = False,
) -> NotificationRecordResult:
    payload = build_notification(
        event_type=event_type,
        title=title,
        body=body,
        scope=scope,
        role=role,
        user_id=user_id,
        data=data,
    )
    normalized_data: dict[str, object] | None = None
    if data:
        safe_data = json_safe_value(dict(data))
        normalized_data = dict(safe_data) if isinstance(safe_data, dict) else None
    try:
        notification_id = insert_notification(
            agency_id=agency_id,
            scope=scope,
            event_type=event_type,
            title=title,
            body=body,
            user_id=user_id,
            role=role,
            data=normalized_data,
            actor=actor,
            is_superuser=is_superuser,
        )
    except (DatabaseError, psycopg.Error) as exc:
        raise NotificationPersistenceError(
            f"Failed to persist notification for event {event_type}"
        ) from exc
    if not isinstance(notification_id, int) or notification_id <= 0:
        raise NotificationPersistenceError(
            f"Notification persistence returned no durable id for event {event_type}"
        )
    return {"notification_id": notification_id, "payload": payload}


def record_notification_in_atomic(
    *,
    agency_id: int | None = None,
    scope: str,
    event_type: str,
    title: str,
    body: str,
    role: str | None = None,
    user_id: int | None = None,
    data: Mapping[str, object] | None = None,
    actor: str | None = None,
    is_superuser: bool = False,
) -> NotificationRecordResult:
    payload = build_notification(
        event_type=event_type,
        title=title,
        body=body,
        scope=scope,
        role=role,
        user_id=user_id,
        data=data,
    )
    normalized_data: dict[str, object] | None = None
    if data:
        safe_data = json_safe_value(dict(data))
        normalized_data = dict(safe_data) if isinstance(safe_data, dict) else None
    try:
        notification_id = insert_notification_in_atomic(
            agency_id=agency_id,
            scope=scope,
            event_type=event_type,
            title=title,
            body=body,
            user_id=user_id,
            role=role,
            data=normalized_data,
        )
    except (DatabaseError, psycopg.Error) as exc:
        raise NotificationPersistenceError(
            f"Failed to persist notification for event {event_type}"
        ) from exc
    if not isinstance(notification_id, int) or notification_id <= 0:
        raise NotificationPersistenceError(
            f"Notification persistence returned no durable id for event {event_type}"
        )
    return {"notification_id": notification_id, "payload": payload}


def record_and_notify(
    *,
    agency_id: int | None = None,
    scope: str,
    event_type: str,
    title: str,
    body: str,
    role: str | None = None,
    user_id: int | None = None,
    data: Mapping[str, object] | None = None,
    actor: str | None = None,
    is_superuser: bool = False,
) -> NotificationRecordResult:
    """Persist a notification and broadcast it to the right group."""
    recorded = record_notification(
        agency_id=agency_id,
        scope=scope,
        event_type=event_type,
        title=title,
        body=body,
        role=role,
        user_id=user_id,
        data=data,
        actor=actor,
        is_superuser=is_superuser,
    )
    _broadcast_notification_after_commit(
        scope=scope,
        payload=dict(recorded["payload"]),
        agency_id=agency_id,
        role=role,
        user_id=user_id,
        event_type=event_type,
    )
    return recorded


def record_and_notify_in_atomic(
    *,
    agency_id: int | None = None,
    scope: str,
    event_type: str,
    title: str,
    body: str,
    role: str | None = None,
    user_id: int | None = None,
    data: Mapping[str, object] | None = None,
    actor: str | None = None,
    is_superuser: bool = False,
) -> NotificationRecordResult:
    """Persist on the current Django transaction and broadcast after commit."""
    with transaction.atomic():
        recorded = record_notification_in_atomic(
            agency_id=agency_id,
            scope=scope,
            event_type=event_type,
            title=title,
            body=body,
            role=role,
            user_id=user_id,
            data=data,
            actor=actor,
            is_superuser=is_superuser,
        )
        resolved_payload: NotificationPayload = dict(recorded["payload"])

        def _after_commit() -> None:
            _broadcast_notification_after_commit(
                scope=scope,
                payload=resolved_payload,
                agency_id=agency_id,
                role=role,
                user_id=user_id,
                event_type=event_type,
            )

        transaction.on_commit(_after_commit)
        return recorded


def _broadcast_notification_after_commit(
    *,
    scope: str,
    payload: NotificationPayload,
    agency_id: int | None,
    role: str | None,
    user_id: int | None,
    event_type: str,
) -> None:
    try:
        broadcast_notification_payload(
            scope=scope,
            payload=payload,
            agency_id=agency_id,
            role=role,
            user_id=user_id,
        )
    except Exception:
        logger.warning(
            "Live notification broadcast failed after persistence for event %s",
            event_type,
            exc_info=True,
        )


def notify_only(
    *,
    scope: str,
    event_type: str,
    title: str,
    body: str,
    role: str | None = None,
    user_id: int | None = None,
    data: Mapping[str, object] | None = None,
) -> NotificationPayload:
    """Broadcast a notification without persisting it."""
    payload = build_notification(
        event_type=event_type,
        title=title,
        body=body,
        scope=scope,
        role=role,
        user_id=user_id,
        data=data,
    )
    broadcast_notification_payload(
        scope=scope,
        payload=payload,
        role=role,
        user_id=user_id,
    )
    return payload


def notify_user(user_id: int, payload: NotificationPayload) -> None:
    notify_group(group_user(user_id), payload)


def notify_agency(agency_id: int, payload: NotificationPayload) -> None:
    notify_group(group_agency(agency_id), payload)


def notify_role(agency_id: int, role: str, payload: NotificationPayload) -> None:
    notify_group(group_role(agency_id, role), payload)


def notify_owner(agency_id: int, payload: NotificationPayload) -> None:
    notify_group(group_owner(agency_id), payload)


def notify_global(payload: NotificationPayload) -> None:
    notify_group(GLOBAL_GROUP, payload)


__all__ = [
    "GLOBAL_GROUP",
    "NotificationPayload",
    "NotificationPersistenceError",
    "NotificationRecordResult",
    "broadcast_notification_payload",
    "build_notification",
    "group_agency",
    "group_owner",
    "group_role",
    "group_user",
    "notify_agency",
    "notify_global",
    "notify_group",
    "notify_owner",
    "notify_role",
    "notify_user",
    "record_notification",
    "record_notification_in_atomic",
    "record_and_notify",
    "record_and_notify_in_atomic",
    "notify_only",
]
