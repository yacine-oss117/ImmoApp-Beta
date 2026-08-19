"""
Location events shared by location-related widgets.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class LocationEvents(QObject):
    """Global events for location list changes."""

    locationsChanged = Signal()


LOCATION_EVENTS = LocationEvents()
