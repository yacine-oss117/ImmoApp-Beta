import json
import logging
import threading
from typing import Any

_thread_locals = threading.local()


def get_correlation_id() -> str | None:
    return getattr(_thread_locals, "correlation_id", None)


def set_correlation_id(correlation_id: str | None) -> None:
    _thread_locals.correlation_id = correlation_id


class CorrelationIdFilter(logging.Filter):
    """Injects correlation_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Formats log records as JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)

        # Add extra fields if available
        if hasattr(record, "data") and isinstance(record.data, dict):
            data.update(record.data)

        return json.dumps(data)
