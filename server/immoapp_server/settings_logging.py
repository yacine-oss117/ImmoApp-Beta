"""
Logging settings.
"""

from __future__ import annotations

import os

from .settings_base import DEBUG

_LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL") or os.environ.get("IMMOAPP_LOG_LEVEL", "INFO")
_LOG_LEVEL = _LOG_LEVEL.strip().upper()
if _LOG_LEVEL not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
    _LOG_LEVEL = "INFO"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "correlation_id": {
            "()": "server.logging_config.CorrelationIdFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "server.logging_config.JsonFormatter",
        },
        "verbose": {
            "format": "{levelname} {asctime} [{correlation_id}] {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["correlation_id"],
            "formatter": "json" if not DEBUG else "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": _LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
        "server": {
            "handlers": ["console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
    },
}

__all__ = ["LOGGING"]
