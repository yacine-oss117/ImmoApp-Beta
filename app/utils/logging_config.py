"""Logging configuration helpers."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from app.core_app.paths import logs_dir

_LOG_CONFIGURED = False


def _resolve_level(level: int | str | None) -> int:
    if isinstance(level, int):
        return level

    candidate = level
    if candidate is None:
        candidate = os.environ.get("IMMOAPP_LOG_LEVEL", "INFO")
    elif not isinstance(candidate, str):
        return logging.INFO

    name = candidate.strip().upper()
    return getattr(logging, name, logging.INFO)


def configure_logging(level: int | str | None = None, log_file: str | None = None) -> None:
    """Configure Python logging with console + rotating file handler.

    This is safe to call multiple times; subsequent calls will not duplicate handlers.
    Logs are stored in the centralized logs directory:
    - Client mode: %LOCALAPPDATA%\\ImmoApp\\logs\\
    - Server mode: %PROGRAMDATA%\\ImmoApp\\logs\\
    """
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    logger = logging.getLogger()

    resolved_level = _resolve_level(level)
    logger.setLevel(resolved_level)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(resolved_level)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))

    # Rotating file handler - use centralized logs directory
    if log_file:
        path = Path(log_file)
    else:
        path = logs_dir() / "app.log"

    fh: logging.Handler | None = None
    try:
        fh = logging.handlers.RotatingFileHandler(
            path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        fh.setLevel(resolved_level)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    except OSError as exc:
        # File logging must never prevent the desktop client from starting.
        # Windows ProgramData ACLs can be temporarily stale after an older
        # elevated bootstrap; run_client.ps1 repairs them, but retain a console
        # fallback for locked/read-only files and other filesystem failures.
        ch.handle(
            logging.LogRecord(
                name=__name__,
                level=logging.WARNING,
                pathname=__file__,
                lineno=0,
                msg=f"File logging unavailable at {path}: {exc}",
                args=(),
                exc_info=None,
            )
        )

    logger.addHandler(ch)
    if fh is not None:
        logger.addHandler(fh)
    _LOG_CONFIGURED = True
