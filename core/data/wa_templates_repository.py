"""
WhatsApp Templates Repository - CRUD operations for message templates.
"""

from __future__ import annotations

from core.data.wa_templates_defaults import DEFAULT_TEMPLATES
from core.matcher.ports.db import DbSession
from core.utils.time import utc_now_iso


def get_all_templates(session: DbSession) -> list[dict[str, object]]:
    """
    Fetch all WhatsApp templates. RLS filters by agency_id.
    """
    rows = session.execute("""
        SELECT id, name, template, is_default, created_at, updated_at
        FROM wa_templates
        WHERE deleted_at IS NULL
        ORDER BY is_default DESC, name ASC
        """).fetchall()
    return [dict(row) for row in rows]


def get_template_by_id(session: DbSession, template_id: int) -> dict[str, object] | None:
    """
    Fetch a template by ID. RLS filters by agency_id.
    """
    row = session.execute(
        "SELECT id, name, template, is_default FROM wa_templates "
        "WHERE id = %s AND deleted_at IS NULL",
        (template_id,),
    ).fetchone()
    return dict(row) if row else None


def get_template_by_name(session: DbSession, name: str) -> dict[str, object] | None:
    """
    Fetch a template by name. RLS filters by agency_id.
    """
    row = session.execute(
        "SELECT id, name, template, is_default FROM wa_templates "
        "WHERE name = %s AND deleted_at IS NULL",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def create_template(
    session: DbSession, name: str, template: str, agency_id: int | None = None
) -> int:
    """
    Create a new custom template.
    """
    # if agency_id is None:
    #     raise ValueError("agency_id is required for templates")
    now = utc_now_iso()
    session.execute(
        """
        INSERT INTO wa_templates (name, template, is_default, created_at, updated_at)
        VALUES (%s, %s, 0, %s, %s)
        RETURNING id
    """,
        (name, template, now, now),
    )
    template_id = session.lastrowid or 0
    return int(template_id)


def update_template(
    session: DbSession, template_id: int, name: str, template: str, agency_id: int | None = None
) -> bool:
    """
    Update an existing template.
    """
    if agency_id is None:
        raise ValueError("agency_id is required for templates")
    now = utc_now_iso()
    agency_filter = " AND agency_id = %s" if agency_id is not None else ""
    session.execute(
        f"""
        UPDATE wa_templates
        SET name = %s,
            template = %s,
            updated_at = %s,
            row_version = row_version + 1
        WHERE id = %s {agency_filter} AND deleted_at IS NULL
    """,
        (name, template, now, template_id, *([agency_id] if agency_id is not None else [])),
    )
    return session.rowcount > 0


def delete_template(session: DbSession, template_id: int, agency_id: int | None = None) -> bool:
    """
    Delete a template by ID.
    """
    if agency_id is None:
        raise ValueError("agency_id is required for templates")
    agency_filter = " AND agency_id = %s" if agency_id is not None else ""
    # Check if it's a default template
    row = session.execute(
        f"SELECT is_default FROM wa_templates WHERE id = %s {agency_filter} AND deleted_at IS NULL",
        (template_id, *([agency_id] if agency_id is not None else [])),
    ).fetchone()
    if not row:
        return False
    if row["is_default"]:
        return False

    now = utc_now_iso()
    session.execute(
        f"""
        UPDATE wa_templates
        SET deleted_at = %s, updated_at = %s, row_version = row_version + 1
        WHERE id = %s {agency_filter} AND deleted_at IS NULL
        """,
        (now, now, template_id, *([agency_id] if agency_id is not None else [])),
    )
    return session.rowcount > 0


def reset_default_templates(session: DbSession, agency_id: int | None = None) -> None:
    """
    Reset all default templates to their original content.
    """
    if agency_id is None:
        raise ValueError("agency_id is required for templates")
    now = utc_now_iso()
    agency_filter = " AND agency_id = %s" if agency_id is not None else ""
    for tpl in DEFAULT_TEMPLATES:
        session.execute(
            f"""
            UPDATE wa_templates
            SET template = %s,
                updated_at = %s,
                row_version = row_version + 1
            WHERE name = %s AND is_default = 1 {agency_filter} AND deleted_at IS NULL
        """,
            (tpl["template"], now, tpl["name"], *([agency_id] if agency_id is not None else [])),
        )
