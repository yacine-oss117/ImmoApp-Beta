"""
Match tab dropdown builders.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.models import Client
from app.services.match_count_state import MatchCountState
from app.utils.i18n import tr_factory

_TR = tr_factory("MatchDropdown")


@dataclass(frozen=True)
class ClientDropdownData:
    """Pre-built dropdown values for match tab."""

    items: list[str]
    id_map: dict[str, int]
    ids_by_index: list[int]


def build_client_display(client: Client, count: int | None) -> str:
    """Build a display string for a single client."""
    name = client.family_name or client.phone or _TR("Client #{id}").format(id=client.id)

    if count is None:
        display = _TR("[?] {name}").format(name=name)
    else:
        display = _TR("[{count}] {name}").format(count=count, name=name)

    if client.phone and client.family_name:
        display += _TR(" | {phone}").format(phone=client.phone)

    return display


def build_client_dropdown_data(
    clients: Iterable[Client],
    counts: MatchCountState,
    min_matches: int,
) -> ClientDropdownData:
    """Build dropdown items and maps from clients and cached counts."""
    items: list[str] = []
    id_map: dict[str, int] = {}
    ids_by_index: list[int] = []

    for client in clients:
        count = counts.get_count(client.id)

        if count is not None and count < min_matches:
            continue

        display = build_client_display(client, count)

        items.append(display)
        id_map[display] = client.id
        ids_by_index.append(client.id)

    return ClientDropdownData(items=items, id_map=id_map, ids_by_index=ids_by_index)
