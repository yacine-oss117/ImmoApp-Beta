"""Transport helpers for importer review page fetch and submit calls."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.services.api_client import api_get, api_post, as_dict


def fetch_review_page(
    *,
    session_id: str,
    page: int,
    page_size: int,
    issue_group: str,
    search_text: str,
    group_key: str,
) -> dict[str, Any]:
    params = {
        "page": max(1, int(page or 1)),
        "page_size": max(1, int(page_size or 50)),
        "mode": "groups",
        "pending_only": "true",
    }
    if issue_group and issue_group != "all":
        params["issue_group"] = issue_group
    if search_text:
        params["search"] = search_text
    if group_key:
        params["group_key"] = group_key
    response = api_get(f"import/{session_id}/review/?{urlencode(params)}")
    data = as_dict(response)
    return {str(key): value for key, value in data.items()}


def submit_review(
    *,
    session_id: str,
    item_decisions: dict[str, dict[str, Any]],
    group_decisions: dict[str, dict[str, Any]],
    skip_item_ids: list[int],
    bulk_operations: list[dict[str, Any]],
) -> dict[str, Any]:
    response = api_post(
        f"import/{session_id}/review/submit/",
        {
            "item_decisions": item_decisions,
            "group_decisions": group_decisions,
            "skip_item_ids": skip_item_ids,
            "bulk_operations": bulk_operations,
        },
    )
    data = as_dict(response)
    return {str(key): value for key, value in data.items()}


def fetch_import_status(*, task_id: str) -> dict[str, Any]:
    response = api_get(f"import/status/{task_id}/")
    data = as_dict(response)
    return {str(key): value for key, value in data.items()}


__all__ = ["fetch_import_status", "fetch_review_page", "submit_review"]
