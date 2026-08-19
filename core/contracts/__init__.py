"""Shared contracts used by both server and desktop runtimes."""

from __future__ import annotations

from .diagnostics_contract import (
    DIAGNOSTICS_EXPORT_FIELDS,
    DIAGNOSTICS_FORBIDDEN_FIELDS,
    DIAGNOSTICS_PAYLOAD_VERSION,
    DIAGNOSTICS_SCHEMA_VERSION,
)
from .http_policy import HTTP_POLICY_VERSION, RoutePolicy
from .idempotency_contract import IDEMPOTENCY_HEADER, LEGACY_IDEMPOTENCY_HEADER
from .offer_photo_lifecycle import (
    PHOTO_DELETE_ORIGIN_LISTING_DELETED,
    PHOTO_DELETE_ORIGIN_LISTING_PURGED,
    PHOTO_DELETE_ORIGIN_MANUAL,
    PHOTO_DELETE_ORIGIN_OFFER_DELETED,
    PHOTO_DELETE_ORIGIN_OFFER_PURGED,
    PHOTO_DELETE_ORIGINS,
    PHOTO_DELETE_PARENT_SCOPE_LISTING,
    PHOTO_DELETE_PARENT_SCOPE_OFFER,
    PHOTO_DELETE_PARENT_SCOPES,
)
from .offer_photo_media import (
    OFFER_PHOTO_CONTENT_TYPES,
    OFFER_PHOTO_EXTENSIONS,
    OFFER_PHOTO_FILE_DIALOG_FILTER,
    OFFER_PHOTO_PURPOSE,
    is_supported_offer_photo_filename,
    offer_photo_content_type_for_filename,
    supported_offer_photo_formats_label,
)
from .semantic_header_registry import SEMANTIC_HEADERS, semantic_header_registry_hash

__all__ = [
    "DIAGNOSTICS_EXPORT_FIELDS",
    "DIAGNOSTICS_FORBIDDEN_FIELDS",
    "DIAGNOSTICS_PAYLOAD_VERSION",
    "DIAGNOSTICS_SCHEMA_VERSION",
    "HTTP_POLICY_VERSION",
    "IDEMPOTENCY_HEADER",
    "LEGACY_IDEMPOTENCY_HEADER",
    "OFFER_PHOTO_CONTENT_TYPES",
    "OFFER_PHOTO_EXTENSIONS",
    "OFFER_PHOTO_FILE_DIALOG_FILTER",
    "OFFER_PHOTO_PURPOSE",
    "PHOTO_DELETE_ORIGIN_LISTING_DELETED",
    "PHOTO_DELETE_ORIGIN_LISTING_PURGED",
    "PHOTO_DELETE_ORIGIN_MANUAL",
    "PHOTO_DELETE_ORIGIN_OFFER_DELETED",
    "PHOTO_DELETE_ORIGIN_OFFER_PURGED",
    "PHOTO_DELETE_ORIGINS",
    "PHOTO_DELETE_PARENT_SCOPE_LISTING",
    "PHOTO_DELETE_PARENT_SCOPE_OFFER",
    "PHOTO_DELETE_PARENT_SCOPES",
    "RoutePolicy",
    "SEMANTIC_HEADERS",
    "is_supported_offer_photo_filename",
    "offer_photo_content_type_for_filename",
    "semantic_header_registry_hash",
    "supported_offer_photo_formats_label",
]
