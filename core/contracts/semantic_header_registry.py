"""Governed semantic header registry shared across server/client."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

SEMANTIC_HEADERS: tuple[str, ...] = (
    "Idempotency-Key",
    "If-Match",
    "X-Feature-Flag",
    "X-Tenant-Mode",
)

_SENSITIVE_REPLAY_HEADERS: tuple[str, ...] = (
    "Authorization",
    "Set-Cookie",
    "Cookie",
)


def normalize_semantic_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return only known semantic headers, normalized and sorted."""
    normalized: dict[str, str] = {}
    lower = {k.lower(): v for k, v in headers.items()}
    for header in SEMANTIC_HEADERS:
        key = header.lower()
        if key not in lower:
            continue
        value = str(lower[key]).strip()
        if not value:
            continue
        normalized[header] = value
    return {k: normalized[k] for k in sorted(normalized)}


def semantic_header_registry_hash() -> str:
    payload = "\n".join(sorted(h.lower() for h in SEMANTIC_HEADERS))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_sensitive_replay_header(header_name: str) -> bool:
    return header_name.strip().lower() in {h.lower() for h in _SENSITIVE_REPLAY_HEADERS}


__all__ = [
    "SEMANTIC_HEADERS",
    "is_sensitive_replay_header",
    "normalize_semantic_headers",
    "semantic_header_registry_hash",
]
