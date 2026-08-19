"""
Sync-ready change feeds for client/offline support.
"""

from __future__ import annotations

from core.data import sync_repo
from core.models import Client, Demande, Listing, Offer
from core.models_crm import Contract, Visit
from server.pg.uow import get_uow


def _fetch_changes(
    *,
    table: str,
    since: str,
    limit: int = 1000,
    after_id: int | None = None,
) -> tuple[list[dict[str, object]], str | None, int | None]:
    with get_uow().session() as session:
        return sync_repo.fetch_changes(
            session,
            table=table,
            since=since,
            limit=limit,
            after_id=after_id,
        )


def fetch_client_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[Client], str | None, int | None]:
    rows, last_changed, last_id = _fetch_changes(
        table="clients", since=since, limit=limit, after_id=after_id
    )
    return [Client.from_row(row) for row in rows], last_changed, last_id


def fetch_listing_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[Listing], str | None, int | None]:
    rows, last_changed, last_id = _fetch_changes(
        table="listings", since=since, limit=limit, after_id=after_id
    )
    return [Listing.from_row(row) for row in rows], last_changed, last_id


def fetch_demande_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[Demande], str | None, int | None]:
    rows, last_changed, last_id = _fetch_changes(
        table="demandes", since=since, limit=limit, after_id=after_id
    )
    return [Demande.from_row(row) for row in rows], last_changed, last_id


def fetch_offer_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[Offer], str | None, int | None]:
    rows, last_changed, last_id = _fetch_changes(
        table="offers", since=since, limit=limit, after_id=after_id
    )
    return [Offer.from_row(row) for row in rows], last_changed, last_id


def fetch_offer_photo_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[dict[str, object]], str | None, int | None]:
    return _fetch_changes(table="offer_photos", since=since, limit=limit, after_id=after_id)


def fetch_visit_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[Visit], str | None, int | None]:
    rows, last_changed, last_id = _fetch_changes(
        table="visits", since=since, limit=limit, after_id=after_id
    )
    return [Visit.from_row(row) for row in rows], last_changed, last_id


def fetch_contract_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[Contract], str | None, int | None]:
    rows, last_changed, last_id = _fetch_changes(
        table="contracts", since=since, limit=limit, after_id=after_id
    )
    return [Contract.from_row(row) for row in rows], last_changed, last_id


def fetch_contract_article_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[dict[str, object]], str | None, int | None]:
    return _fetch_changes(table="contract_articles", since=since, limit=limit, after_id=after_id)


def fetch_custom_location_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[dict[str, object]], str | None, int | None]:
    return _fetch_changes(table="custom_locations", since=since, limit=limit, after_id=after_id)


def fetch_template_changes(
    *, since: str, limit: int = 1000, after_id: int | None = None
) -> tuple[list[dict[str, object]], str | None, int | None]:
    return _fetch_changes(table="wa_templates", since=since, limit=limit, after_id=after_id)


def fetch_agency_settings_changes(
    *, since: str, limit: int = 1000
) -> tuple[list[dict[str, object]], str | None, int | None]:
    return _fetch_changes(table="agency_settings", since=since, limit=limit)
