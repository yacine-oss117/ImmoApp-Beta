"""
Helpers to resolve lookup IDs and canonical names for payloads.
"""

from __future__ import annotations

from collections.abc import Mapping

from core.data import lookup_tables
from core.models_cast import as_optional_int

from .uow import PgSession


def resolve_lookup_fields(session: PgSession, payload: Mapping[str, object]) -> dict[str, object]:
    """Return a copy of payload with type/action/wilaya ids + canonical names resolved."""
    data = dict(payload)

    type_id = as_optional_int(data.get("type_id"))
    action_id = as_optional_int(data.get("action_id"))
    wilaya_id = as_optional_int(data.get("wilaya_id"))
    if type_id == 0:
        type_id = None
    if action_id == 0:
        action_id = None
    if wilaya_id == 0:
        wilaya_id = None

    type_id, type_name = lookup_tables.resolve_property_type(
        session, type_id, _string_or_empty(data.get("type"))
    )
    action_id, action_name = lookup_tables.resolve_action(
        session, action_id, _string_or_empty(data.get("action"))
    )
    wilaya_id, wilaya_name = lookup_tables.resolve_wilaya(
        session, wilaya_id, _string_or_empty(data.get("wilaya"))
    )

    data.update(
        {
            "type_id": type_id,
            "type": type_name,
            "action_id": action_id,
            "action": action_name,
            "wilaya_id": wilaya_id,
            "wilaya": wilaya_name,
        }
    )
    return data


def _string_or_empty(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
