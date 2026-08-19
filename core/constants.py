"""
Centralized constants for Yacine Real Estate Matcher.

This module provides a single source of truth for application-wide constants,
eliminating duplication across files and making configuration changes easier.
"""

# Application identity (used by QSettings for persistent storage)
ORG = "GIMIMMO"
APP = "YacineRealEstateMatcher"

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
