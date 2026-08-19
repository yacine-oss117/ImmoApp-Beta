"""
Service-layer helpers for per-record visibility and ACLs.
"""

from __future__ import annotations

from core.data import record_acl as data
from server.pg.uow import get_current_agency_id, get_uow
from server.services.errors import ConflictError, NotFoundError

_VISIBILITY_VALUES = {"agency", "restricted"}


def _normalize_visibility(value: str | None) -> str:
    if not value:
        return "agency"
    value = value.strip().lower()
    if value not in _VISIBILITY_VALUES:
        raise ValueError("visibility must be 'agency' or 'restricted'")
    return value


def _validate_user_ids(user_ids: list[int], *, agency_id: int) -> list[int]:
    if not user_ids:
        return []
    ids = sorted({int(uid) for uid in user_ids if int(uid) > 0})
    if not ids:
        return []
    from server.accounts.models import User

    rows = list(User.objects.filter(id__in=ids, agency_id=agency_id).values_list("id", flat=True))
    rows_set = {int(v) for v in rows}
    missing = [uid for uid in ids if uid not in rows_set]
    if missing:
        raise ValueError("Some users are not part of this agency")
    return ids


def get_record_visibility(table: str, record_id: int) -> dict[str, object]:
    with get_uow().session() as session:
        snapshot = data.get_record_snapshot(session, table=table, record_id=record_id)
        if not snapshot:
            raise NotFoundError("Record not found")
        acl_users = data.list_record_acl(session, table=table, record_id=record_id)
        snapshot["allowed_user_ids"] = acl_users
        snapshot["visibility"] = snapshot.get("visibility") or "agency"
        return snapshot


def set_record_visibility(
    *,
    table: str,
    record_id: int,
    visibility: str | None,
    allowed_user_ids: list[int] | None,
    row_version: int | None = None,
) -> None:
    agency_id = get_current_agency_id()
    if agency_id is None:
        raise RuntimeError("agency_id is required for record visibility updates")
    if row_version is None:
        raise ValueError("row_version is required for visibility updates")

    visibility_value = _normalize_visibility(visibility)
    users = _validate_user_ids(allowed_user_ids or [], agency_id=agency_id)

    previous_visibility: str | None = None
    with get_uow().transaction() as session:
        snapshot = data.get_record_snapshot(session, table=table, record_id=record_id)
        if snapshot:
            previous_visibility = snapshot.get("visibility") or "agency"
        updated = data.update_visibility(
            session,
            table=table,
            record_id=record_id,
            visibility=visibility_value,
            row_version=row_version,
        )
        if updated == 0:
            current = data.get_record_snapshot(session, table=table, record_id=record_id)
            if current is None:
                raise NotFoundError("Record not found")
            raise ConflictError(
                "Record was updated by someone else",
                current_version=int(current.get("row_version") or 0),
                current_record=current,
            )

        if visibility_value == "restricted" and not users:
            owner_id = None
            snapshot = data.get_record_snapshot(session, table=table, record_id=record_id)
            if snapshot:
                owner_id = snapshot.get("owner_user_id")
            if isinstance(owner_id, int) and owner_id > 0:
                users = [owner_id]

        data.replace_record_acl(
            session,
            table=table,
            record_id=record_id,
            user_ids=users if visibility_value == "restricted" else [],
        )
        if _should_rebuild_matches(
            table,
            previous_visibility,
            visibility_value,
            users,
        ):
            session.on_commit(
                lambda resolved_table=table, resolved_record_id=int(
                    record_id
                ): _enqueue_visibility_rebuild(
                    resolved_table,
                    resolved_record_id,
                )
            )


def _should_rebuild_matches(
    table: str,
    previous_visibility: str | None,
    next_visibility: str,
    users: list[int],
) -> bool:
    if table not in {"clients", "demandes", "offers", "listings"}:
        return False
    if previous_visibility is None:
        return True
    if previous_visibility != next_visibility:
        return True
    if next_visibility == "restricted":
        # ACL list updates can affect visibility even if mode stays restricted.
        return True
    return False


def _fetch_listing_offer_ids(record_id: int) -> list[int]:
    with get_uow().session() as session:
        rows = session.execute(
            "SELECT id FROM offers WHERE listing_id = %s AND deleted_at IS NULL",
            (record_id,),
        ).fetchall()
    return [int(row["id"]) for row in rows if row.get("id") is not None]


def _enqueue_visibility_rebuild(table: str, record_id: int) -> None:
    from .match_jobs import (
        enqueue_rebuild_client_pairs,
        enqueue_rebuild_demande_pairs,
        enqueue_rebuild_offer_pairs,
    )

    if table == "clients":
        enqueue_rebuild_client_pairs(record_id)
    elif table == "demandes":
        enqueue_rebuild_demande_pairs(record_id)
    elif table == "offers":
        enqueue_rebuild_offer_pairs(record_id)
    elif table == "listings":
        for offer_id in _fetch_listing_offer_ids(record_id):
            enqueue_rebuild_offer_pairs(offer_id)
