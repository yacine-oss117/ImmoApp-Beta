"""
Tests for i18n helpers.
"""

from __future__ import annotations

import logging

import pytest
from PySide6.QtCore import QSettings

import app.utils.i18n as i18n_module
from app.utils.i18n import _language_candidates, install_translator, resolve_language

pytestmark = pytest.mark.ui


def _make_settings(tmp_path: object) -> QSettings:
    path = str(tmp_path) + "/settings.ini"
    return QSettings(path, QSettings.Format.IniFormat)


def test_language_candidates_handles_locale_variants() -> None:
    assert _language_candidates("fr-FR") == ["fr_FR", "fr"]
    assert _language_candidates("ar_DZ") == ["ar_DZ", "ar"]
    assert _language_candidates("en") == ["en"]
    assert _language_candidates("") == []


def test_resolve_language_returns_explicit_setting(tmp_path: object) -> None:
    settings = _make_settings(tmp_path)
    settings.setValue("ui/language", "fr_FR")
    assert resolve_language(settings) == "fr_FR"


def test_resolve_language_defaults_to_system_locale(tmp_path: object) -> None:
    settings = _make_settings(tmp_path)
    settings.setValue("ui/language", "auto")
    resolved = resolve_language(settings)
    assert isinstance(resolved, str)
    assert resolved


def test_install_translator_skips_missing_english_debug_noise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
    qapp,
) -> None:
    monkeypatch.setattr(i18n_module, "I18N_DIR", tmp_path)
    caplog.set_level(logging.DEBUG, logger=i18n_module.logger.name)
    install_translator(qapp, "en_US")
    assert not any("No translation found" in rec.message for rec in caplog.records)


def test_install_translator_logs_missing_non_english_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
    qapp,
) -> None:
    monkeypatch.setattr(i18n_module, "I18N_DIR", tmp_path)
    caplog.set_level(logging.DEBUG, logger=i18n_module.logger.name)
    install_translator(qapp, "fr_FR")
    assert any("No translation found" in rec.message for rec in caplog.records)
