"""
Contract article operations for CRM (Postgres-backed).
"""

from __future__ import annotations

from core.data import contract_articles_repository as articles
from server.pg.uow import get_uow


def create_article(
    contract_id: int,
    article_number: int,
    title: str,
    content: str,
    *,
    is_standard: bool = False,
    is_required: bool = False,
    actor: str | None = None,
) -> int:
    """Create a new article (clause) for a contract."""
    with get_uow().transaction(actor=actor) as session:
        return articles.create_article(
            session,
            contract_id,
            article_number,
            title,
            content,
            is_standard,
            is_required,
        )


def update_article(
    article_id: int,
    title: str,
    content: str,
    *,
    row_version: int | None = None,
    actor: str | None = None,
) -> bool:
    """Update an article's title and content."""
    with get_uow().transaction(actor=actor) as session:
        return articles.update_article(session, article_id, title, content, row_version=row_version)


def delete_article(article_id: int, *, actor: str | None = None) -> bool:
    """Delete an article from a contract."""
    with get_uow().transaction(actor=actor) as session:
        return articles.delete_article(session, article_id)


def get_articles_for_contract(contract_id: int) -> list[dict[str, object]]:
    """List all articles associated with a specific contract."""
    with get_uow().session() as session:
        return articles.get_articles_for_contract(session, contract_id)


def renumber_articles(contract_id: int, *, actor: str | None = None) -> None:
    """Ensure article numbers for a contract are sequential and start from 1."""
    with get_uow().transaction(actor=actor) as session:
        articles.renumber_articles(session, contract_id)


def copy_standard_clauses(
    contract_id: int,
    context: dict[str, str],
    *,
    actor: str | None = None,
) -> int:
    """Clone all standard clauses into a specific contract, performing template variable replacement."""
    with get_uow().transaction(actor=actor) as session:
        return articles.copy_standard_clauses_to_contract(session, contract_id, context)
