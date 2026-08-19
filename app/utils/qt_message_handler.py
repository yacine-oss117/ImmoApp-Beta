"""Qt message handler integration."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler

_logger = logging.getLogger("Qt")


def _qt_platform_is_headless() -> bool:
    platform = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
    return platform in {"offscreen", "minimal"}


def _is_ignored_qt_warning(message: str) -> bool:
    if "QFont::setPointSize: Point size <= 0" in message:
        # Ignore noisy Qt warning when platform font reports pixel-size only.
        return True
    if not _qt_platform_is_headless():
        return False
    if "QFontDatabase: Cannot find font directory" in message:
        # PySide's headless plugins can emit this even when the desktop app is
        # otherwise healthy. It is not actionable for local importer runs.
        return True
    if message.strip() == "This plugin does not support raise()":
        return True
    return False


def _qt_message_handler(msg_type: QtMsgType, context: QMessageLogContext, message: str) -> None:
    # Map Qt message types to Python logging levels
    if _is_ignored_qt_warning(message):
        return
    level = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }.get(msg_type, logging.INFO)

    file_name = getattr(context, "file", None)
    line_no = getattr(context, "line", None)
    fileinfo = f"{file_name}:{line_no}" if file_name else ""
    if fileinfo:
        _logger.log(level, "%s (%s)", message, fileinfo)
    else:
        _logger.log(level, "%s", message)


def install_qt_message_logging() -> None:
    """Route Qt's internal qDebug/qWarning/etc to Python logging."""
    try:
        qInstallMessageHandler(_qt_message_handler)
    except RuntimeError:
        # Fallback: avoid crashing if handler cannot be set in some environments
        _logger.debug("Qt message handler installation skipped.", exc_info=True)
