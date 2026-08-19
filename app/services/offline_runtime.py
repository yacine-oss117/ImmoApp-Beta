"""Runtime flags for offline create and reconciliation behavior."""

from __future__ import annotations

import os


def offline_creates_enabled() -> bool:
    value = os.environ.get("IMMOAPP_OFFLINE_CREATES_ENABLED", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


__all__ = ["offline_creates_enabled"]
