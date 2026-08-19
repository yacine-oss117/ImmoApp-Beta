"""
Map preview helpers for ListingsTabV2.
"""

from __future__ import annotations

import logging
from typing import Protocol

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton

from app.models import Offer
from app.utils.geo import map_link_to_url, parse_lat_lon
from app.utils.i18n import tr_factory
from app.utils.text_safety import set_label_plain_text

logger = logging.getLogger(__name__)
_TR = tr_factory("ListingsTabV2")


class _MapPreviewHost(Protocol):
    _details_label: QLabel
    _coords_label: QLabel
    _open_map_btn: QPushButton
    _map_url: str | None


def set_map_preview(host: _MapPreviewHost, offer: Offer | None) -> None:
    """Update the map preview based on the selected offer."""
    if offer is None:
        set_label_plain_text(host._details_label, _TR("Select an offer to view its location."))
        set_label_plain_text(host._coords_label, _TR("No coordinates loaded."))
        host._open_map_btn.setEnabled(False)
        host._map_url = None
        return

    coords = None
    if offer.latitude is not None and offer.longitude is not None:
        coords = (float(offer.latitude), float(offer.longitude))
    elif offer.link:
        coords = parse_lat_lon(offer.link)

    if coords:
        set_label_plain_text(host._details_label, _TR("Offer #{id}").format(id=offer.id))
        lat_text = f"{coords[0]:.6f}".rstrip("0").rstrip(".")
        lon_text = f"{coords[1]:.6f}".rstrip("0").rstrip(".")
        set_label_plain_text(
            host._coords_label, _TR("Lat: {lat}, Lon: {lon}").format(lat=lat_text, lon=lon_text)
        )
    else:
        set_label_plain_text(host._details_label, _TR("Offer #{id}").format(id=offer.id))
        if offer.link:
            set_label_plain_text(host._coords_label, _TR("Link: {link}").format(link=offer.link))
        else:
            set_label_plain_text(host._coords_label, _TR("No coordinates loaded."))

    host._map_url = map_link_to_url(
        offer.link or "",
        latitude=coords[0] if coords else None,
        longitude=coords[1] if coords else None,
    )
    host._open_map_btn.setEnabled(host._map_url is not None)


def open_details_map(host: _MapPreviewHost) -> None:
    """Open the current map URL in the browser."""
    if not host._map_url:
        return
    QDesktopServices.openUrl(QUrl(host._map_url))


__all__ = ["open_details_map", "set_map_preview"]
