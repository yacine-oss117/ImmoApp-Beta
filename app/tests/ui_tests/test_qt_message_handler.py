from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QtMsgType

from app.utils import qt_message_handler as module


def test_offscreen_raise_warning_is_ignored(monkeypatch) -> None:
    logged: list[tuple[int, str]] = []

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(
        module._logger, "log", lambda level, fmt, *args: logged.append((level, fmt))
    )

    module._qt_message_handler(
        QtMsgType.QtWarningMsg,
        SimpleNamespace(file=None, line=0),
        "This plugin does not support raise()",
    )

    assert logged == []


def test_non_ignored_warning_still_logs(monkeypatch) -> None:
    logged: list[tuple[int, str, tuple[object, ...]]] = []

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(
        module._logger,
        "log",
        lambda level, fmt, *args: logged.append((level, fmt, args)),
    )

    module._qt_message_handler(
        QtMsgType.QtWarningMsg,
        SimpleNamespace(file="demo.cpp", line=7),
        "Real warning",
    )

    assert logged
    level, fmt, args = logged[0]
    assert level
    assert fmt == "%s (%s)"
    assert args == ("Real warning", "demo.cpp:7")
