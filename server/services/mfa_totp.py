"""TOTP MFA helpers (RFC 6238)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import urllib.parse
from datetime import datetime, timezone

_TOTP_DIGITS = 6
_TOTP_PERIOD_SECONDS = int(os.environ.get("IMMOAPP_TOTP_PERIOD_SECONDS", "30"))
_TOTP_WINDOW = int(os.environ.get("IMMOAPP_TOTP_WINDOW", "1"))
_TOTP_ISSUER = os.environ.get("IMMOAPP_TOTP_ISSUER", "ImmoApp").strip() or "ImmoApp"


def generate_secret(*, byte_length: int = 20) -> str:
    raw = secrets.token_bytes(max(16, int(byte_length)))
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def provisioning_uri(*, username: str, secret: str, issuer: str | None = None) -> str:
    label = urllib.parse.quote(f"{(issuer or _TOTP_ISSUER)}:{username}")
    query = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": issuer or _TOTP_ISSUER,
            "algorithm": "SHA1",
            "digits": str(_TOTP_DIGITS),
            "period": str(_TOTP_PERIOD_SECONDS),
        }
    )
    return f"otpauth://totp/{label}?{query}"


def _decode_secret(secret: str) -> bytes:
    normalized = str(secret or "").strip().replace(" ", "").upper()
    if not normalized:
        raise ValueError("TOTP secret is required")
    padding = "=" * ((8 - (len(normalized) % 8)) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def _hotp(secret: str, counter: int) -> str:
    key = _decode_secret(secret)
    msg = int(counter).to_bytes(8, byteorder="big")
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], byteorder="big") & 0x7FFFFFFF
    code = truncated % (10**_TOTP_DIGITS)
    return f"{code:0{_TOTP_DIGITS}d}"


def verify_code(
    *,
    secret: str,
    code: str | None,
    now: datetime | None = None,
    window: int | None = None,
) -> bool:
    normalized_code = str(code or "").strip()
    if len(normalized_code) != _TOTP_DIGITS or not normalized_code.isdigit():
        return False
    current = now or datetime.now(timezone.utc)
    counter = int(current.timestamp()) // _TOTP_PERIOD_SECONDS
    tolerance = _TOTP_WINDOW if window is None else max(0, int(window))
    for offset in range(-tolerance, tolerance + 1):
        if secrets.compare_digest(_hotp(secret, counter + offset), normalized_code):
            return True
    return False


__all__ = ["generate_secret", "provisioning_uri", "verify_code"]
