"""Shared idempotency contract constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IDEMPOTENCY_HEADER = "Idempotency-Key"
LEGACY_IDEMPOTENCY_HEADER = "X-Idempotency-Key"
IDEMPOTENCY_RESPONSE_HEADERS_ALLOWLIST: tuple[str, ...] = (
    "Content-Type",
    "ETag",
    "X-Request-Id",
    "X-Request-Policy",
    "Idempotency-Status",
    "Retry-After",
)
IDEMPOTENCY_TTL_SECONDS_DEFAULT = 24 * 60 * 60
IDEMPOTENCY_IN_PROGRESS_WAIT_SECONDS = 3
IDEMPOTENCY_RETRY_AFTER_SECONDS = 2
IDEMPOTENCY_MAX_RESPONSE_BYTES = 256 * 1024
IDEMPOTENCY_HMAC_PAYLOAD_VERSION = "v1"
SUPPORTED_HMAC_PAYLOAD_VERSIONS: tuple[str, ...] = (IDEMPOTENCY_HMAC_PAYLOAD_VERSION,)

IdempotencyState = Literal["in_progress", "completed", "failed_transient"]

ERR_KEY_REUSE_MISMATCH = "IDEMPOTENCY_KEY_REUSE_MISMATCH"
ERR_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
ERR_TAMPERED = "IDEMPOTENCY_RECORD_TAMPERED"
ERR_UNVERIFIABLE = "IDEMPOTENCY_RECORD_UNVERIFIABLE"


@dataclass(frozen=True)
class IdempotencyScope:
    agency_id: int
    normalized_route: str
    method: str
    idempotency_key: str


__all__ = [
    "ERR_IN_PROGRESS",
    "ERR_KEY_REUSE_MISMATCH",
    "ERR_TAMPERED",
    "ERR_UNVERIFIABLE",
    "IDEMPOTENCY_HEADER",
    "IDEMPOTENCY_HMAC_PAYLOAD_VERSION",
    "SUPPORTED_HMAC_PAYLOAD_VERSIONS",
    "IDEMPOTENCY_IN_PROGRESS_WAIT_SECONDS",
    "IDEMPOTENCY_MAX_RESPONSE_BYTES",
    "IDEMPOTENCY_RESPONSE_HEADERS_ALLOWLIST",
    "IDEMPOTENCY_RETRY_AFTER_SECONDS",
    "IDEMPOTENCY_TTL_SECONDS_DEFAULT",
    "LEGACY_IDEMPOTENCY_HEADER",
    "IdempotencyScope",
    "IdempotencyState",
]
