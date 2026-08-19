"""Compatibility facade for the idempotency engine."""

from __future__ import annotations

from server.api.idempotency_engine import (
    IdempotencyContext,
    check_idempotency,
    purge_expired_idempotency_records,
    store_idempotency,
)

__all__ = [
    "IdempotencyContext",
    "check_idempotency",
    "purge_expired_idempotency_records",
    "store_idempotency",
]
