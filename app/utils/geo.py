"""Geo helpers for coordinate parsing and map URLs (client-side)."""

from __future__ import annotations

import re
from urllib.parse import urlencode

_COORD_PAIR_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$")
_URL_PATTERNS = (
    re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)"),
    re.compile(r"[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)"),
    re.compile(r"!3d(-?\d+(?:\.\d+)?)[!&]+4d(-?\d+(?:\.\d+)?)"),
)


def parse_lat_lon(value: str) -> tuple[float, float] | None:
    """
    Parse latitude/longitude from plain text or a map URL.

    Accepts:
    - "lat,lon" or "lat lon"
    - Google Maps URLs containing "@lat,lon" or "q=lat,lon"
    - URLs containing "!3dLAT!4dLON"
    """
    text = (value or "").strip()
    if not text:
        return None

    match = _COORD_PAIR_RE.match(text)
    if match:
        return _coerce_pair(match.group(1), match.group(2))

    for pattern in _URL_PATTERNS:
        match = pattern.search(text)
        if match:
            return _coerce_pair(match.group(1), match.group(2))

    return None


def build_osm_url(lat: float, lon: float, zoom: int = 17) -> str:
    """Return a shareable OpenStreetMap URL."""
    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map={zoom}/{lat}/{lon}"


def build_osm_embed_url(lat: float, lon: float, span: float = 0.01) -> str:
    """Return an embeddable OpenStreetMap URL for previews."""
    min_lon = lon - span
    max_lon = lon + span
    min_lat = lat - span
    max_lat = lat + span
    params = {
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "layer": "mapnik",
        "marker": f"{lat},{lon}",
    }
    return "https://www.openstreetmap.org/export/embed.html?" + urlencode(params)


def map_link_to_url(
    value: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> str | None:
    """Convert a raw link or coordinates into a browser-friendly map URL."""
    if latitude is not None and longitude is not None and _coords_valid(latitude, longitude):
        return build_osm_url(latitude, longitude)

    coords = parse_lat_lon(value)
    if coords:
        return build_osm_url(coords[0], coords[1])

    text = (value or "").strip()
    if text.startswith(("http://", "https://")):
        return text
    return None


def _coerce_pair(lat_raw: str, lon_raw: str) -> tuple[float, float] | None:
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _coords_valid(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0
