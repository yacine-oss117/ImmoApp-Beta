"""
Quick UI startup smoke check for API mode.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT)

# Headless-safe mode + light startup avoids long-running network tasks.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IMMOAPP_OFFLINE", "1")
os.environ.setdefault("IMMOAPP_STARTUP_LIGHT", "1")
os.environ.setdefault("IMMOAPP_SKIP_SCHEMA_INIT", "1")

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def test_startup() -> bool:
    _app = QApplication(sys.argv)
    try:
        window = MainWindow()
        print("MainWindow initialized successfully")
        window.close()
        return True
    except Exception as exc:
        print(f"Startup failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    raise SystemExit(0 if test_startup() else 1)
