"""
Tests for QSettings schema validation helpers.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from app.utils.settings_schema import (
    SCHEMA_VERSION_KEY,
    SETTINGS_SCHEMA_VERSION,
    apply_settings_schema,
)


def _make_settings(tmp_path: object) -> QSettings:
    path = str(tmp_path) + "/settings.ini"
    return QSettings(path, QSettings.Format.IniFormat)


def test_apply_settings_schema_sets_defaults(tmp_path: object) -> None:
    settings = _make_settings(tmp_path)
    apply_settings_schema(settings)

    assert settings.value("time/offline_mode", None, bool) is False
    assert settings.value("time/use_ntp", None, bool) is True
    assert settings.value("ui/density", None, str) == "compact"
    assert settings.value("ui/max_threadpool", None, int) == 4
    assert settings.value(SCHEMA_VERSION_KEY, 0, int) == SETTINGS_SCHEMA_VERSION


def test_apply_settings_schema_coerces_values(tmp_path: object) -> None:
    settings = _make_settings(tmp_path)
    settings.setValue("time/use_ntp", "false")
    settings.setValue("ui/max_threadpool", "8")
    settings.setValue("time/manual_tz", 123)
    settings.setValue("ui/density", "invalid")

    apply_settings_schema(settings)

    assert settings.value("time/use_ntp", None, bool) is False
    assert settings.value("ui/max_threadpool", None, int) == 8
    assert settings.value("time/manual_tz", None, str) == "123"
    assert settings.value("ui/density", None, str) == "compact"


def test_apply_settings_schema_migrates_legacy_comfortable_density(tmp_path: object) -> None:
    settings = _make_settings(tmp_path)
    settings.setValue(SCHEMA_VERSION_KEY, 2)
    settings.setValue("ui/density", "comfortable")

    apply_settings_schema(settings)

    assert settings.value("ui/density", None, str) == "compact"
