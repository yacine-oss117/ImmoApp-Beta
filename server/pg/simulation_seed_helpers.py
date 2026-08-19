"""
Helper functions for simulation seeding.
"""

from __future__ import annotations

import hashlib
import random

from core.data.locations import extract_wilaya_from_location


def fake_phone(seed: int) -> str:
    return f"0550{seed:06d}"[-10:]


def pick_choice(rng: random.Random, values: list[str]) -> str:
    return values[rng.randrange(len(values))]


def pick_scope(rng: random.Random, nationwide_prob: float, wilaya_only_prob: float) -> str:
    roll = rng.random()
    if roll < nationwide_prob:
        return "nationwide"
    if roll < nationwide_prob + wilaya_only_prob:
        return "wilaya"
    return "location"


def index_locations(locations: list[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for loc in locations:
        wilaya = extract_wilaya_from_location(loc)
        if not wilaya:
            continue
        mapping.setdefault(wilaya, []).append(loc)
    return mapping


def pick_wilaya_location(
    rng: random.Random,
    *,
    scope: str,
    wilayas: list[str],
    locations: list[str],
    wilaya_locations: dict[str, list[str]],
) -> tuple[str, str]:
    if scope == "nationwide":
        return "", ""
    if scope == "wilaya":
        return pick_choice(rng, wilayas), ""
    return pick_listing_location(
        rng,
        wilayas=wilayas,
        locations=locations,
        wilaya_locations=wilaya_locations,
    )


def pick_listing_location(
    rng: random.Random,
    *,
    wilayas: list[str],
    locations: list[str],
    wilaya_locations: dict[str, list[str]],
) -> tuple[str, str]:
    if wilaya_locations:
        wilaya = pick_choice(rng, list(wilaya_locations.keys()))
        location = pick_choice(rng, wilaya_locations[wilaya])
        return wilaya, location
    location = locations[0] if locations else ""
    wilaya = extract_wilaya_from_location(location) or (wilayas[0] if wilayas else "")
    return wilaya, location


def pick_surface(rng: random.Random, prop_type: str) -> float:
    ranges = {
        "studio": (25.0, 55.0),
        "apartment": (45.0, 140.0),
        "house": (80.0, 240.0),
        "villa": (150.0, 450.0),
        "business": (40.0, 180.0),
        "land": (100.0, 600.0),
        "other": (60.0, 220.0),
    }
    low, high = ranges.get(prop_type, (50.0, 180.0))
    return round(rng.uniform(low, high), 2)


def beds_from_surface(surface: float, rng: random.Random) -> int:
    base = max(1, int(surface // 35))
    return max(1, min(6, base + rng.randint(-1, 1)))


def pick_budget(rng: random.Random, surface: float, action: str) -> float:
    if action in {"buy", "sell"}:
        price_per_m2 = rng.randint(80_000, 220_000)
    else:
        price_per_m2 = rng.randint(300, 1500)
    return surface * float(price_per_m2)


def pick_floor(rng: random.Random, prop_type: str) -> int:
    if prop_type in {"land", "house"}:
        return 0
    return rng.randint(0, 12)


def round_currency(value: float) -> float:
    return round(value / 1000.0) * 1000.0


def coords_from_location(location: str) -> tuple[float, float]:
    raw = location or "algeria"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    seed = int(digest[:12], 16)
    lat = 19.0 + (seed % 1800) / 100.0
    lon = -8.0 + ((seed // 1800) % 2000) / 100.0
    return round(lat, 6), round(lon, 6)


def map_link(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat:.6f},{lon:.6f}"
