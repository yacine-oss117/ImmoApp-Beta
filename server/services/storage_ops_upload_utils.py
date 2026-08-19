"""Upload helper utilities."""

from __future__ import annotations

import uuid
from pathlib import Path


def build_object_key(agency_id: int, purpose: str, filename: str | None) -> str:
    """Generate a storage object key."""
    safe_name = Path(filename or "").name or "blob"
    return f"agency/{agency_id}/{purpose}/{uuid.uuid4().hex}_{safe_name}"
