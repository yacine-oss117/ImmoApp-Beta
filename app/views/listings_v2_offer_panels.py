"""
Offer panel helpers for ListingsTabV2.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol

from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.widgets.offer_panel import OfferPanel
from core.models import Offer

logger = logging.getLogger(__name__)


class _OfferPanelHost(Protocol):
    _offer_panels: list[OfferPanel]
    _offers_container: QWidget
    _offers_layout: QVBoxLayout
    _listing_section: Any
    refresh_match_counts_cb: Any

    def refresh_table(self, force_reload: bool = True) -> None: ...


def add_offer_panel(
    host: _OfferPanelHost, data: Offer | Mapping[str, object] | None = None
) -> OfferPanel:
    """Add a new offer panel."""
    try:
        host._listing_section.expand()
    except Exception:
        pass
    host._offers_container.setVisible(True)
    num = len(host._offer_panels) + 1
    panel = OfferPanel(offer_number=num, parent=host._offers_container)
    panel.delete_requested.connect(lambda p=panel: remove_offer_panel(host, p))
    if data:
        panel.set_data(data)
    host._offer_panels.append(panel)
    host._offers_layout.addWidget(panel)

    return panel


def on_offer_expanded(host: _OfferPanelHost, expanded_panel: OfferPanel) -> None:
    """Compatibility no-op; editor panels no longer use accordion behavior."""
    _ = host
    _ = expanded_panel


def remove_offer_panel(
    host: _OfferPanelHost,
    panel: OfferPanel,
    *,
    delete_persisted: bool = True,
) -> None:
    """Remove an offer panel."""
    if panel not in host._offer_panels:
        return
    deleted_persisted = False
    if delete_persisted and panel.offer_id > 0:
        from app.services.offer_repository import delete_offer

        delete_offer(panel.offer_id)
        deleted_persisted = True
    host._offer_panels.remove(panel)
    host._offers_layout.removeWidget(panel)
    panel.deleteLater()
    for i, existing in enumerate(host._offer_panels):
        existing.set_number(i + 1)
    if deleted_persisted:
        host.refresh_table()
        if host.refresh_match_counts_cb:
            host.refresh_match_counts_cb()


__all__ = ["add_offer_panel", "on_offer_expanded", "remove_offer_panel"]
