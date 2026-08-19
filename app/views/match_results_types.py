"""
Typed dependencies for match results rendering.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.models import Listing, Offer
from app.views.base import QWidget


@dataclass(frozen=True)
class MatchResultsDeps:
    """Dependencies required to render match results."""

    get_listing_by_id: Callable[[int], Listing | None]
    create_action_buttons: Callable[[int, Offer, QWidget | None], QWidget]
    on_phone_click: Callable[[], None]
    on_position_click: Callable[[], None]
    on_load_more: Callable[[], None]
    on_show_all: Callable[[], None]
    allow_pagination: bool
