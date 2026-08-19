"""
Contract Articles Repository - CRUD operations for dynamic contract articles.
"""

from __future__ import annotations

from core.data.errors import ConflictError, NotFoundError
from core.matcher.ports.db import DbSession
from core.models_cast import as_int
from core.utils.time import utc_now_iso


def create_article(
    session: DbSession,
    contract_id: int,
    article_number: int,
    title: str,
    content: str,
    is_standard: bool = False,
    is_required: bool = False,
) -> int:
    """
    Create a new article for a contract.
    """
    now = utc_now_iso()
    session.execute(
        """
        INSERT INTO contract_articles 
        (agency_id, contract_id, article_number, title, content, is_standard, is_required, created_at, updated_at)
        SELECT
            c.agency_id,
            c.id,
            %s, %s, %s, %s, %s, %s, %s
        FROM contracts c
        WHERE c.id = %s AND c.deleted_at IS NULL
        RETURNING id
    """,
        (
            article_number,
            title,
            content,
            1 if is_standard else 0,
            1 if is_required else 0,
            now,
            now,
            contract_id,
        ),
    )
    article_id = session.lastrowid or 0
    if not article_id:
        raise NotFoundError("Contract not found")
    return article_id


def get_articles_for_contract(session: DbSession, contract_id: int) -> list[dict[str, object]]:
    """
    Fetch all articles for a specific contract, ordered by article_number.
    """
    rows = session.execute(
        """
        SELECT id, contract_id, article_number, title, content, is_standard, is_required, row_version
        FROM contract_articles
        WHERE contract_id = %s AND deleted_at IS NULL
        ORDER BY article_number ASC
    """,
        (contract_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_article(
    session: DbSession,
    article_id: int,
    title: str,
    content: str,
    *,
    row_version: int | None = None,
) -> bool:
    """
    Update an existing article's title and content.
    """
    now = utc_now_iso()
    if row_version is not None:
        session.execute(
            """
            UPDATE contract_articles
            SET title = %s,
                content = %s,
                updated_at = %s,
                row_version = row_version + 1
            WHERE id = %s AND deleted_at IS NULL AND row_version = %s
            """,
            (title, content, now, article_id, row_version),
        )
        if session.rowcount == 0:
            row = session.execute(
                "SELECT * FROM contract_articles WHERE id = %s",
                (article_id,),
            ).fetchone()
            if row:
                current_version = as_int(row.get("row_version"), default=0)
                current_record = dict(row)
                raise ConflictError(
                    "Article was updated by another user. Please refresh and try again.",
                    current_version=current_version or None,
                    current_record=current_record,
                )
        return session.rowcount > 0
    session.execute(
        """
        UPDATE contract_articles
        SET title = %s,
            content = %s,
            updated_at = %s,
            row_version = row_version + 1
        WHERE id = %s AND deleted_at IS NULL
        """,
        (title, content, now, article_id),
    )
    return session.rowcount > 0


def delete_article(session: DbSession, article_id: int) -> bool:
    """
    Delete an article by ID.
    """
    # Check if it's required
    row = session.execute(
        "SELECT is_required FROM contract_articles WHERE id = %s AND deleted_at IS NULL",
        (article_id,),
    ).fetchone()
    if not row or row["is_required"]:
        return False

    now = utc_now_iso()
    session.execute(
        """
        UPDATE contract_articles
        SET deleted_at = %s, updated_at = %s, row_version = row_version + 1
        WHERE id = %s AND deleted_at IS NULL
        """,
        (now, now, article_id),
    )
    return session.rowcount > 0


def renumber_articles(session: DbSession, contract_id: int) -> None:
    """
    Renumber all articles in a contract sequentially (1, 2, 3...).
    """
    # Get current articles in order
    rows = session.execute(
        """
        SELECT id FROM contract_articles
        WHERE contract_id = %s
        ORDER BY article_number ASC
    """,
        (contract_id,),
    ).fetchall()

    # Update each with new sequential number
    for idx, row in enumerate(rows, start=1):
        session.execute(
            """
            UPDATE contract_articles
            SET article_number = %s,
                updated_at = %s,
                row_version = row_version + 1
            WHERE id = %s AND deleted_at IS NULL
            """,
            (idx, utc_now_iso(), row["id"]),
        )


def delete_all_articles_for_contract(session: DbSession, contract_id: int) -> int:
    """
    Delete all articles for a contract.
    """
    now = utc_now_iso()
    session.execute(
        """
        UPDATE contract_articles
        SET deleted_at = %s, updated_at = %s, row_version = row_version + 1
        WHERE contract_id = %s AND deleted_at IS NULL
        """,
        (now, now, contract_id),
    )
    return session.rowcount


def copy_standard_clauses_to_contract(
    session: DbSession, contract_id: int, context: dict[str, str]
) -> int:
    """
    Copy all standard clauses to a contract with placeholders filled.
    """
    from core.data.standard_clauses import get_standard_clauses, render_all_clauses

    clauses = get_standard_clauses()
    rendered = render_all_clauses(clauses, context)

    count = 0
    for clause in rendered:
        create_article(
            session=session,
            contract_id=contract_id,
            article_number=clause["number"],
            title=f"Article {clause['number']} - {clause['title']}",
            content=clause["content"],
            is_standard=True,
            is_required=clause.get("is_required", False),
        )
        count += 1

    return count
