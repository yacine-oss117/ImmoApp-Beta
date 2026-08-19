from __future__ import annotations

DEFAULT_OPENBAO_REQUIRED_KEYS: tuple[str, ...] = (
    "DJANGO_SECRET_KEY",
    "ALE_KEY_VERSION",
    "ALE_MASTER_KEY",
    "ALE_SEARCH_SECRET",
    "ALE_KDF_SALT",
    "IMMOAPP_IDEMPOTENCY_HMAC_KEY",
)

__all__ = ["DEFAULT_OPENBAO_REQUIRED_KEYS"]
