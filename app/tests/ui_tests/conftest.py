"""
UI-only pytest fixtures.

This conftest is intentionally isolated so headless/server test runs do not
require PySide6 at collection time.
"""

from __future__ import annotations

import os

import pytest

# Make UI tests reliable in headless/CI environments.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IMMOAPP_STARTUP_LIGHT", "1")

# Skips ALL tests in this directory and its children if PySide6 is missing.
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Provide a session-scoped QApplication instance."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
