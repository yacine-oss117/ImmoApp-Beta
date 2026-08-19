"""ImmoApp server package."""

from __future__ import annotations

import os

if os.environ.get("IMMOAPP_SKIP_CELERY_APP", "").strip().lower() in {"1", "true", "yes", "on"}:
    celery_app = None
else:
    from .celery import celery_app


__all__ = ["celery_app"]
