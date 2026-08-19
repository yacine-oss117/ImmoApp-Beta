"""Tests for geo coordinate parsing helpers."""

from __future__ import annotations

import pytest

from app.utils.geo import map_link_to_url, parse_lat_lon


def test_parse_lat_lon_plain() -> None:
    coords = parse_lat_lon("36.7529,3.0420")
    assert coords == pytest.approx((36.7529, 3.0420))
    coords = parse_lat_lon("36.7529 3.0420")
    assert coords == pytest.approx((36.7529, 3.0420))


def test_parse_lat_lon_google_at() -> None:
    url = "https://www.google.com/maps/place/Algiers/@36.7529,3.0420,12z"
    coords = parse_lat_lon(url)
    assert coords == pytest.approx((36.7529, 3.0420))


def test_parse_lat_lon_google_query() -> None:
    url = "https://maps.google.com/?q=36.7529,3.0420"
    coords = parse_lat_lon(url)
    assert coords == pytest.approx((36.7529, 3.0420))


def test_parse_lat_lon_google_3d_4d() -> None:
    url = "https://www.google.com/maps/place/foo/data=!3d36.7529!4d3.0420"
    coords = parse_lat_lon(url)
    assert coords == pytest.approx((36.7529, 3.0420))


def test_parse_lat_lon_invalid() -> None:
    assert parse_lat_lon("not a coordinate") is None


def test_map_link_to_url() -> None:
    url = map_link_to_url("36.7529,3.0420")
    assert url is not None
    assert url.startswith("https://www.openstreetmap.org/")

    url = map_link_to_url("https://example.com")
    assert url == "https://example.com"
