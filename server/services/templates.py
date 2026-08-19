"""
Postgres-backed WhatsApp templates operations.

Note: Read helpers accept agency_id=None for superuser cross-tenant reads.
Write helpers still enforce agency_id for tenant scoping.
"""

from __future__ import annotations

from collections.abc import Mapping

from core.data import wa_templates_repository as data
from core.data.wa_templates_render import render_template as _render_template
from server.pg.uow import get_uow


def get_all_templates() -> list[dict[str, object]]:
    """Retrieve all WhatsApp templates for an agency."""
    with get_uow().session() as session:
        return data.get_all_templates(session)


def get_template_by_id(template_id: int) -> dict[str, object] | None:
    """Retrieve a WhatsApp template by its unique ID."""
    with get_uow().session() as session:
        return data.get_template_by_id(session, template_id)


def get_template_by_name(name: str) -> dict[str, object] | None:
    """Retrieve a WhatsApp template by its name."""
    with get_uow().session() as session:
        return data.get_template_by_name(session, name)


def create_template(name: str, template: str, *, actor: str | None = None) -> int:
    """Create a new WhatsApp template."""
    with get_uow().transaction(actor=actor) as session:
        return data.create_template(session, name, template)


def update_template(
    template_id: int,
    name: str,
    template: str,
    *,
    actor: str | None = None,
) -> bool:
    """Update an existing WhatsApp template."""
    with get_uow().transaction(actor=actor) as session:
        return data.update_template(session, template_id, name, template)


def delete_template(template_id: int, *, actor: str | None = None) -> bool:
    """Delete a WhatsApp template."""
    with get_uow().transaction(actor=actor) as session:
        return data.delete_template(session, template_id)


def reset_default_templates(*, actor: str | None = None) -> None:
    """Restore WhatsApp templates to their default values."""
    with get_uow().transaction(actor=actor) as session:
        data.reset_default_templates(session)


def render_template(template_text: str, context: Mapping[str, object]) -> str:
    """Replace placeholders in template text with values from the context."""
    return _render_template(template_text, context)
