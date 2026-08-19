"""
WhatsApp Templates Service - Manages templates via Unit of Work.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.models_cast import as_int
from app.services.api_client import (
    ApiError,
    api_delete_resilient,
    api_get,
    api_post,
    api_post_resilient,
    api_put_resilient,
    as_dict,
)

__all__ = [
    "create_template",
    "delete_template",
    "get_all_templates",
    "get_template_by_id",
    "get_template_by_name",
    "render_template",
    "reset_default_templates",
    "update_template",
]


def get_all_templates() -> list[dict[str, object]]:
    """Fetch all WhatsApp templates using UoW."""
    payload = as_dict(api_get("/templates"))
    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def get_template_by_id(template_id: int) -> dict[str, object] | None:
    """Fetch a template by ID using UoW."""
    try:
        response = api_get(f"/templates/{template_id}")
    except ApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    payload = as_dict(response)
    return payload or None


def get_template_by_name(name: str) -> dict[str, object] | None:
    """Fetch a template by name using UoW."""
    items = get_all_templates()
    for item in items:
        if str(item.get("name") or "").strip().lower() == name.strip().lower():
            return item
    return None


def create_template(name: str, template: str) -> int:
    """Create a new custom template using UoW."""
    payload = as_dict(api_post("/templates", {"name": name, "template": template}))
    return as_int(payload.get("id"), default=0)


def update_template(template_id: int, name: str, template: str) -> bool:
    """Update an existing template using UoW."""
    result = api_put_resilient(
        f"/templates/{template_id}",
        {"name": name, "template": template},
        dedupe_key=f"PUT:/templates/{template_id}",
        label="template.update",
    )
    if result.queued:
        return True
    payload = as_dict(result.payload)
    return bool(payload.get("updated"))


def delete_template(template_id: int) -> bool:
    """Delete a template by ID using UoW."""
    result = api_delete_resilient(
        f"/templates/{template_id}",
        dedupe_key=f"DELETE:/templates/{template_id}",
        label="template.delete",
    )
    if result.queued:
        return True
    payload = as_dict(result.payload)
    return bool(payload.get("deleted"))


def reset_default_templates() -> None:
    """Reset all default templates using UoW."""
    api_post_resilient(
        "/templates/reset-defaults",
        dedupe_key="POST:/templates/reset-defaults",
        label="template.reset_defaults",
    )


def render_template(template_text: str, context: Mapping[str, object]) -> str:
    """Render a template (pure client-side logic)."""
    result = template_text
    for key, value in context.items():
        placeholder = "{" + key + "}"
        result = result.replace(placeholder, str(value) if value else "")
    return result
