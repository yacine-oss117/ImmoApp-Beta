"""
Record-level ACL helpers.
"""

from __future__ import annotations

from core.data.sql_identifiers import validate_identifier
from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int, row_optional_int, row_optional_str

ACL_TABLES = {
    "clients",
    "listings",
    "demandes",
    "offers",
    "visits",
    "contracts",
}


def get_record_snapshot(
    session: DbSession,
    *,
    table: str,
    record_id: int,
) -> dict[str, object] | None:
    validate_identifier(table, allowed=ACL_TABLES, kind="table")
    row = session.execute(
        f"""
        SELECT id, visibility, owner_user_id, owner_role, row_version
        FROM {table}
        WHERE id = %s
        """,
        (record_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row_int(row, "id"),
        "visibility": row_optional_str(row, "visibility"),
        "owner_user_id": row_optional_int(row, "owner_user_id"),
        "owner_role": row_optional_str(row, "owner_role"),
        "row_version": row_optional_int(row, "row_version"),
    }


def update_visibility(
    session: DbSession,
    *,
    table: str,
    record_id: int,
    visibility: str,
    row_version: int | None = None,
) -> int:
    validate_identifier(table, allowed=ACL_TABLES, kind="table")
    params: list[object] = [visibility, record_id]
    sql = (
        f"UPDATE {table} "
        "SET visibility = %s, "
        "    updated_at = CURRENT_TIMESTAMP, "
        "    row_version = row_version + 1 "
        "WHERE id = %s"
    )
    if row_version is not None:
        sql += " AND row_version = %s"
        params.append(row_version)
    session.execute(sql, params)
    return session.rowcount


def list_record_acl(session: DbSession, *, table: str, record_id: int) -> list[int]:
    validate_identifier(table, allowed=ACL_TABLES, kind="table")
    rows = session.execute(
        "SELECT user_id FROM record_acl WHERE table_name = %s AND record_id = %s "
        "ORDER BY user_id",
        (table, record_id),
    ).fetchall()
    return [row_int(row, "user_id") for row in rows]


def replace_record_acl(
    session: DbSession,
    *,
    table: str,
    record_id: int,
    user_ids: list[int],
) -> None:
    validate_identifier(table, allowed=ACL_TABLES, kind="table")
    session.execute(
        "DELETE FROM record_acl WHERE table_name = %s AND record_id = %s",
        (table, record_id),
    )
    if not user_ids:
        return
    session.executemany(
        """
        INSERT INTO record_acl (table_name, record_id, user_id, created_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (table_name, record_id, user_id) DO NOTHING
        """,
        [(table, record_id, user_id) for user_id in user_ids],
    )
