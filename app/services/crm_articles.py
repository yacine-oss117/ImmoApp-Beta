"""
CRM contract article operations.
"""

from __future__ import annotations

from typing import Any

from app.models_cast import as_int
from app.services.api_client import (
    ApiError,
    api_get,
    api_post,
    api_post_resilient,
    as_dict,
)
from app.services.offline_account_scope import get_active_account_scope
from app.services.offline_capabilities import require_supported_offline_action
from app.services.offline_entity_mutations import (
    OfflineCreateRequest,
    create_entity,
    delete_entity,
    update_entity,
)
from app.services.offline_projection import list_projection_records
from app.services.offline_types import OfflineEntityRef


def _require_synced_contract(contract_id: int) -> None:
    if int(contract_id) < 0:
        require_supported_offline_action("contract_article", "renumber")


def create_article(
    contract_id: int,
    article_number: int,
    title: str,
    content: str,
    is_standard: bool = False,
    is_required: bool = False,
) -> int:
    """Create a contract article using UoW."""
    payload_in = {
        "article_number": article_number,
        "title": title,
        "content": content,
        "is_standard": is_standard,
        "is_required": is_required,
    }
    try:
        created_id = create_entity(
            OfflineCreateRequest(
                entity_type="contract_article",
                path_template="/crm/contracts/{contract_id}/articles",
                request_body=payload_in,
                projection_data={**payload_in, "contract_id": int(contract_id)},
                path_refs={
                    "contract_id": OfflineEntityRef(
                        entity_type="contract",
                        local_id=int(contract_id),
                    )
                },
                label="article.create",
            )
        )
    except ApiError as exc:
        raise ValueError(exc.message) from exc
    return int(created_id)


def update_article(
    article_id: int, title: str, content: str, row_version: int | None = None
) -> bool:
    """Update a contract article using UoW."""
    payload_in: dict[str, object] = {"title": title, "content": content}
    if row_version is not None:
        payload_in["row_version"] = row_version
    try:
        result = update_entity(
            "contract_article",
            article_id,
            f"/crm/articles/{article_id}",
            payload_in,
            dedupe_key=f"PUT:/crm/articles/{article_id}",
            label="article.update",
        )
    except ApiError as exc:
        if exc.status_code == 409:
            raise ValueError("Article changed since you opened it. Refresh and try again.") from exc
        if exc.status_code == 404:
            raise ValueError("Article not found.") from exc
        raise ValueError(exc.message) from exc
    if result.queued:
        return True
    payload = as_dict(result.payload)
    return bool(payload.get("updated"))


def delete_article(article_id: int) -> bool:
    """Delete a contract article using UoW."""
    result = delete_entity(
        "contract_article",
        article_id,
        f"/crm/articles/{article_id}",
        dedupe_key=f"DELETE:/crm/articles/{article_id}",
        label="article.delete",
    )
    if result.queued:
        return True
    payload = as_dict(result.payload)
    return bool(payload.get("deleted"))


def get_articles_for_contract(contract_id: int) -> list[dict[str, object]]:
    """Fetch articles for a contract using UoW."""
    server_items: list[dict[str, object]] = []
    if int(contract_id) > 0:
        try:
            payload = as_dict(api_get(f"/crm/contracts/{contract_id}/articles"))
        except RuntimeError:
            payload = {}
        items = payload.get("items")
        if isinstance(items, list):
            server_items = [item for item in items if isinstance(item, dict)]
    return _merge_article_projections(int(contract_id), server_items)


def renumber_articles(contract_id: int) -> None:
    """Renumber articles for a contract using UoW."""
    _require_synced_contract(contract_id)
    api_post_resilient(
        f"/crm/contracts/{contract_id}/articles/renumber",
        dedupe_key=f"POST:/crm/contracts/{contract_id}/articles/renumber",
        label="article.renumber",
    )


def copy_standard_clauses(contract_id: int, context: dict[str, str]) -> int:
    """Copy standard clauses to a contract using UoW."""
    if int(contract_id) < 0:
        require_supported_offline_action("contract_article", "copy_standard_clauses")
    payload = as_dict(
        api_post(
            f"/crm/contracts/{contract_id}/clauses",
            {"context": context},
        )
    )
    return as_int(payload.get("count"), default=0)


def _merge_article_projections(
    contract_id: int, server_items: list[dict[str, object]]
) -> list[dict[str, object]]:
    scope = get_active_account_scope()
    projection_rows = (
        [
            record
            for record in list_projection_records("contract_article", scope=scope)
            if as_int(record.data.get("contract_id"), default=0) == int(contract_id)
        ]
        if scope is not None
        else []
    )
    projection_by_id = {int(record.local_id): record for record in projection_rows}
    merged: list[dict[str, object]] = []
    seen_ids: set[int] = set()

    for item in server_items:
        item_id = as_int(item.get("id"), default=0)
        if item_id <= 0:
            continue
        record = projection_by_id.get(item_id)
        if record is not None and record.sync_status == "pending_delete":
            seen_ids.add(item_id)
            continue
        server_item = dict(item)
        if record is not None:
            server_item.update(record.data)
            server_item["sync_status"] = record.sync_status
            server_item["sync_error"] = record.sync_error
            server_item["is_local_only"] = record.is_local_only
        merged.append(server_item)
        seen_ids.add(item_id)

    for record in projection_rows:
        item_id = int(record.local_id)
        if item_id in seen_ids or record.sync_status == "pending_delete":
            continue
        projection_item: dict[str, Any] = dict(record.data)
        projection_item.setdefault("id", int(record.server_id or record.local_id))
        projection_item["sync_status"] = record.sync_status
        projection_item["sync_error"] = record.sync_error
        projection_item["is_local_only"] = record.is_local_only
        merged.append(projection_item)

    merged.sort(
        key=lambda item: (
            as_int(item.get("article_number"), default=0),
            as_int(item.get("id"), default=0),
        )
    )
    return merged
