"""ALE maintenance operations shared by tasks and CLI scripts."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Iterable

from core.blind_index import get_search_key_version
from core.data import db_schema_meta
from core.encryption import EncryptionError, get_encryption_service
from core.utils.common import sanitize_text
from server.pg.uow import PgSession, admin_transaction

logger = logging.getLogger("ale_maintenance")

PII_TABLES: dict[str, list[str]] = {
    "clients": [
        "family_name_enc",
        "phone_enc",
        "remarks_enc",
        "family_name_search_idx",
        "phone_search_idx",
    ],
    "listings": [
        "family_name_enc",
        "phone_enc",
        "remarks_enc",
        "family_name_search_idx",
        "phone_search_idx",
    ],
    "demandes": ["remarks_enc", "locations_enc"],
    "offers": ["remarks_enc", "location_enc"],
    "visits": ["notes_enc"],
    "contracts": ["amount_enc", "deposit_enc", "terms_enc", "notes_enc"],
}

SEARCH_TABLES: dict[str, list[tuple[str, str]]] = {
    "clients": [
        ("family_name_enc", "family_name_search_idx"),
        ("phone_enc", "phone_search_idx"),
    ],
    "listings": [
        ("family_name_enc", "family_name_search_idx"),
        ("phone_enc", "phone_search_idx"),
    ],
}

ALE_TABLES: dict[str, list[str]] = {
    "clients": ["family_name_enc", "phone_enc", "remarks_enc"],
    "listings": ["family_name_enc", "phone_enc", "remarks_enc"],
    "demandes": ["remarks_enc", "locations_enc"],
    "offers": ["remarks_enc", "location_enc"],
    "visits": ["notes_enc"],
    "contracts": ["amount_enc", "deposit_enc", "terms_enc", "notes_enc"],
}

_VERSION_RE = re.compile(r"^v\d+$")


def purge_ale_pii(*, days: int, dry_run: bool) -> int:
    total = 0
    interval_sql = f"NOW() - INTERVAL '{int(days)} days'"
    for table, columns in PII_TABLES.items():
        set_sql = ", ".join(f"{col} = NULL" for col in columns)
        where_sql = f"deleted_at IS NOT NULL AND deleted_at < {interval_sql}"
        count_sql = f"SELECT COUNT(*) AS cnt FROM {table} WHERE {where_sql}"
        with admin_transaction() as session:
            row = session.execute(count_sql).fetchone()
        raw_count = row["cnt"] if row else 0
        if isinstance(raw_count, (int, float, str)):
            count = int(raw_count)
        else:
            count = 0
        if count and not dry_run:
            with admin_transaction() as session:
                session.execute(f"UPDATE {table} SET {set_sql} WHERE {where_sql}")
        logger.info("Table %s: %s rows eligible", table, count)
        total += count
    if total and not dry_run:
        with admin_transaction() as session:
            db_schema_meta.ensure_meta_table(session)
            db_schema_meta.set_meta(
                session, "ale_pii_purge_at", datetime.now(timezone.utc).isoformat()
            )
    return total


def _iter_reindex_rows(
    table: str, columns: Iterable[tuple[str, str]], force: bool, limit: int | None
) -> list[dict[str, object]]:
    select_cols = ["id"] + [enc for enc, _ in columns] + [idx for _, idx in columns]
    where: list[str] = []
    for enc_col, idx_col in columns:
        if force:
            where.append(f"({enc_col} IS NOT NULL AND {enc_col} <> '')")
        else:
            where.append(f"({enc_col} IS NOT NULL AND {enc_col} <> '' AND {idx_col} IS NULL)")
    where_sql = " OR ".join(where) if where else "FALSE"
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    sql = f"SELECT {', '.join(select_cols)} FROM {table} WHERE {where_sql}{limit_sql}"
    with admin_transaction() as session:
        rows = session.execute(sql).fetchall()
    return [dict(row) for row in rows]


def _reindex_row(
    row: dict[str, object],
    table: str,
    columns: list[tuple[str, str]],
    dry_run: bool,
) -> int:
    enc = get_encryption_service()
    updates: dict[str, object] = {}
    changed = 0
    for enc_col, idx_col in columns:
        raw_val = row.get(enc_col)
        if not raw_val or not isinstance(raw_val, str):
            continue
        try:
            plaintext = enc.decrypt(raw_val)
        except EncryptionError as exc:
            logger.error("Failed decrypt for %s.%s id=%s: %s", table, enc_col, row.get("id"), exc)
            continue
        updates[idx_col] = sanitize_text(plaintext)
        changed += 1
    if updates and not dry_run:
        set_parts = [f"{col} = immoapp_hash_trigrams(%s)" for col in updates.keys()]
        params = list(updates.values())
        set_sql = ", ".join(set_parts)
        params.append(row["id"])
        sql = f"UPDATE {table} SET {set_sql} WHERE id = %s"
        with admin_transaction() as session:
            session.execute(sql, tuple(params))
    return changed


def reindex_ale_search(*, dry_run: bool, force: bool, limit: int | None) -> int:
    total = 0
    for table, columns in SEARCH_TABLES.items():
        rows = _iter_reindex_rows(table, columns, force, limit)
        logger.info("Table %s: %s rows to reindex", table, len(rows))
        for row in rows:
            total += _reindex_row(row, table, columns, dry_run)
    if total and not dry_run:
        with admin_transaction() as session:
            db_schema_meta.ensure_meta_table(session)
            db_schema_meta.set_meta(
                session, "ale_search_rotation_at", datetime.now(timezone.utc).isoformat()
            )
            db_schema_meta.set_meta(
                session, "ale_search_rotation_version", get_search_key_version()
            )
    return total


def _iter_candidate_rows(
    table: str, columns: Iterable[str], current_prefix: str, limit: int | None
) -> list[dict[str, object]]:
    select_cols = ["id"] + list(columns)
    where_clauses: list[str] = []
    params: list[object] = []
    for col in columns:
        where_clauses.append(f"({col} IS NOT NULL AND {col} <> '' AND {col} NOT LIKE %s)")
        params.append(current_prefix)
    where_sql = " OR ".join(where_clauses) if where_clauses else "FALSE"
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    sql = f"SELECT {', '.join(select_cols)} FROM {table} WHERE {where_sql}{limit_sql}"
    with admin_transaction() as session:
        rows = session.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def _rotate_row(
    row: dict[str, object],
    table: str,
    columns: list[str],
    current_prefix: str,
    dry_run: bool,
) -> tuple[bool, int]:
    enc = get_encryption_service()
    updates: dict[str, object] = {}
    rotated_count = 0
    for col in columns:
        value = row.get(col)
        if not value or not isinstance(value, str):
            continue
        if value.startswith(current_prefix):
            continue
        try:
            plaintext = enc.decrypt(value)
            updates[col] = enc.encrypt(plaintext)
            rotated_count += 1
        except EncryptionError as exc:
            logger.error("Failed decrypt for %s.%s id=%s: %s", table, col, row.get("id"), exc)

    if updates and not dry_run:
        set_sql = ", ".join(f"{col} = %s" for col in updates.keys())
        params = list(updates.values()) + [row["id"]]
        sql = f"UPDATE {table} SET {set_sql} WHERE id = %s"
        with admin_transaction() as session:
            session.execute(sql, tuple(params))
    return bool(updates), rotated_count


def rotate_ale_keys(*, dry_run: bool, limit: int | None) -> int:
    enc = get_encryption_service()
    current_prefix = f"{enc.current_key_id}:"
    total_rotated = 0
    for table, columns in ALE_TABLES.items():
        rows = _iter_candidate_rows(table, columns, current_prefix, limit)
        logger.info("Table %s: %s candidates", table, len(rows))
        for row in rows:
            updated, rotated = _rotate_row(row, table, columns, current_prefix, dry_run)
            if updated:
                total_rotated += rotated
    if total_rotated and not dry_run:
        with admin_transaction() as session:
            db_schema_meta.ensure_meta_table(session)
            db_schema_meta.set_meta(
                session, "ale_key_rotation_at", datetime.now(timezone.utc).isoformat()
            )
            db_schema_meta.set_meta(session, "ale_key_rotation_version", enc.current_key_id)
    return total_rotated


def _normalize_version(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    if not value:
        return None
    if not _VERSION_RE.match(value):
        raise ValueError("version must match vN format (e.g., v1, v2)")
    return value


def _get_current(session: PgSession) -> str:
    current = db_schema_meta.get_meta(session, "ale_search_key_version")
    return _normalize_version(current) or "v1"


def start_ale_search_rotation(*, to_version: str) -> dict[str, str]:
    target = _normalize_version(to_version)
    if target is None:
        raise ValueError("to_version is required")

    with admin_transaction() as session:
        db_schema_meta.ensure_meta_table(session)
        current = _get_current(session)
        if current == target:
            return {"current": current, "previous": "", "status": "noop"}

        db_schema_meta.set_meta(session, "ale_search_key_prev_version", current)
        db_schema_meta.set_meta(session, "ale_search_key_version", target)
        db_schema_meta.set_meta(
            session, "ale_search_rotation_at", datetime.now(timezone.utc).isoformat()
        )
        db_schema_meta.set_meta(session, "ale_search_rotation_version", target)

    return {"current": target, "previous": current, "status": "started"}


def finalize_ale_search_rotation() -> dict[str, str]:
    with admin_transaction() as session:
        db_schema_meta.ensure_meta_table(session)
        current = _get_current(session)
        db_schema_meta.set_meta(session, "ale_search_key_prev_version", "")
        db_schema_meta.set_meta(
            session, "ale_search_rotation_at", datetime.now(timezone.utc).isoformat()
        )
    return {"current": current, "previous": "", "status": "finalized"}


__all__ = [
    "purge_ale_pii",
    "reindex_ale_search",
    "rotate_ale_keys",
    "start_ale_search_rotation",
    "finalize_ale_search_rotation",
]
