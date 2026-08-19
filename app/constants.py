"""
Centralized constants for Yacine Real Estate Matcher (client-side).
"""

from __future__ import annotations

import os

# Application identity (used by QSettings for persistent storage)
ORG = os.environ.get("IMMOAPP_QSETTINGS_ORG", "GIMIMMO")
APP = os.environ.get("IMMOAPP_QSETTINGS_APP", "YacineRealEstateMatcher")

# Client/Listing types and actions
CLIENT_TYPES = ["", "apartment", "house", "business", "land", "other"]
CLIENT_ACTIONS = ["buy", "rent"]
CLIENT_FURNISHED = ["any", "yes", "no"]

LISTING_TYPES = ["", "apartment", "house", "business", "land", "other"]
LISTING_ACTIONS = ["sell", "rent"]
LISTING_FURNISHED = ["yes", "no", "any"]

# CRM statuses
VISIT_STATUSES = ["scheduled", "completed", "cancelled"]
CONTRACT_STATUSES = ["draft", "active", "completed", "cancelled"]
CONTRACT_TYPES = ["buy", "rent"]

# Cache settings
CACHE_TTL_SEC = 30.0  # seconds before cache expires

# Shared widget ranges
BEDS_RANGE = (0, 50)
SURFACE_RANGE = (0, 99_999)
BUDGET_RANGE = (0, 999_999_999)
FLOOR_RANGE = (0, 100)
FLEX_RANGE = (0, 100)  # Percentage

__all__ = [
    "APP",
    "BEDS_RANGE",
    "BUDGET_RANGE",
    "CACHE_TTL_SEC",
    "CLIENT_ACTIONS",
    "CLIENT_FURNISHED",
    "CLIENT_TYPES",
    "CONTRACT_STATUSES",
    "CONTRACT_TYPES",
    "FLEX_RANGE",
    "FLOOR_RANGE",
    "LISTING_ACTIONS",
    "LISTING_FURNISHED",
    "LISTING_TYPES",
    "ORG",
    "SURFACE_RANGE",
    "VISIT_STATUSES",
]
