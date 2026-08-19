# ruff: noqa: E402
# --------------------------------------------------------------------------
# BOOTSTRAP: Self-Restarting Redirection
# This ensures even 'python -m app.main' is 100% clean.
# --------------------------------------------------------------------------
import os
import sys


def _default_appdata_root() -> str:
    env_root = os.environ.get("IMMOAPP_APPDATA_ROOT")
    if env_root:
        return env_root
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not base:
            base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(base, "ImmoApp")
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return os.path.join(xdg, "ImmoApp")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "ImmoApp")


_APPDATA_ROOT = _default_appdata_root()
_PYCACHE_DIR = os.path.join(_APPDATA_ROOT, "cache", "pycache")
_DONT_WRITE_BYTECODE = os.environ.get("PYTHONDONTWRITEBYTECODE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

if not _DONT_WRITE_BYTECODE and os.environ.get("PYTHONPYCACHEPREFIX") != _PYCACHE_DIR:
    # 1. Prepare the environment
    os.environ["PYTHONPYCACHEPREFIX"] = _PYCACHE_DIR
    try:
        os.makedirs(_PYCACHE_DIR, exist_ok=True)
    except Exception:
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    # 2. Re-execute the application with the correct environment
    if getattr(sys, "frozen", False):
        pass
    else:
        import subprocess

        result = subprocess.run([sys.executable] + sys.argv)
        sys.exit(result.returncode)
else:
    # We are in the redirected process.
    # Try to clean up the 'leak' created by the first run if it exists.
    try:
        import shutil

        _local_cache = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "__pycache__"
        )
        if os.path.exists(_local_cache):
            shutil.rmtree(_local_cache, ignore_errors=True)
    except Exception:
        pass

# --------------------------------------------------------------------------
# Proceed with path setup and imports
# --------------------------------------------------------------------------
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import logging
import threading
import types

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from app.constants import APP, ORG
from app.core_app.paths import ensure_appdata_dirs
from app.services.db_backup import backup_database
from app.ui.font_loader import SYSTEM_FONT_FALLBACKS, load_bundled_fonts
from app.ui.theme_manager import apply_theme
from app.utils.i18n import install_translator
from app.utils.logging_config import configure_logging
from app.utils.qt_message_handler import install_qt_message_logging
from app.utils.settings_schema import apply_settings_schema


def _install_crash_backup() -> None:
    """Register crash handlers to persist a last-ditch backup."""
    logger = logging.getLogger(__name__)

    def _prompt_crash_diagnostics(exc_type: type[BaseException]) -> None:
        app = QApplication.instance()
        if app is None:
            return
        try:
            from app.widgets.diagnostics_actions import send_diagnostics_interactive

            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("Application Error")
            box.setText("The app hit an unexpected error.")
            box.setInformativeText("You can send a signed diagnostics report for support.")
            send_btn = box.addButton("Send Diagnostics", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is send_btn:
                send_diagnostics_interactive(
                    None,
                    route_name="desktop.crash",
                    normalized_route="/desktop/crash",
                    policy_id="desktop.crash",
                    error_code=f"UNHANDLED_{exc_type.__name__}",
                )
        except Exception:
            logger.warning("Crash diagnostics prompt failed", exc_info=True)

    def _handle_exception(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: types.TracebackType | None,
    ) -> None:
        logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            backup_database("crash", force=True)
        except Exception:
            logger.error("Crash backup failed", exc_info=True)
        _prompt_crash_diagnostics(exc_type)
        sys.__excepthook__(exc_type, exc, tb)

    def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        exc_info: tuple[type[BaseException], BaseException, types.TracebackType | None] | None
        if args.exc_value is None:
            exc_info = None
        else:
            exc_info = (args.exc_type, args.exc_value, args.exc_traceback)
        logger.critical("Unhandled thread exception", exc_info=exc_info)
        try:
            backup_database("thread-crash", force=True)
        except Exception:
            logger.error("Thread crash backup failed", exc_info=True)
        if hasattr(threading, "__excepthook__"):
            threading.__excepthook__(args)

    sys.excepthook = _handle_exception
    threading.excepthook = _handle_thread_exception


def main() -> None:
    """Main entry point for the application bootstrap and Qt event loop."""
    import logging

    logger = logging.getLogger(__name__)

    # Ensure app architecture is ready
    ensure_appdata_dirs()
    configure_logging()
    install_qt_message_logging()
    try:
        from app.services.onboarding_analytics import increment_app_launch_count

        increment_app_launch_count()
    except Exception:
        logger.debug("Failed to update onboarding launch counter", exc_info=True)

    _install_crash_backup()
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except (AttributeError, RuntimeError):
        logger.warning("Failed to set high DPI policy", exc_info=True)

    app = QApplication(sys.argv)
    # Prefer bundled open fonts for consistent rendering, fallback to system.
    bundled_families = load_bundled_fonts()
    fallback_families = list(SYSTEM_FONT_FALLBACKS)
    ordered_families: list[str] = []
    for family in [*bundled_families, *fallback_families]:
        if family not in ordered_families:
            ordered_families.append(family)
    preferred_family = ordered_families[0] if ordered_families else "Segoe UI"
    f = QFont(preferred_family, 10)
    if hasattr(f, "setFamilies"):
        try:
            f.setFamilies(ordered_families)
        except Exception:
            logger.debug("Unable to set font family fallback list", exc_info=True)
    if f.pointSize() <= 0:
        f.setPointSize(10)
    app.setFont(f)
    apply_theme(app)
    prev_quit_on_close = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)

    # Enforce safe defaults for time settings to prevent accidental offline
    s = QSettings(ORG, APP)
    apply_settings_schema(s)
    s.setValue("time/offline_mode", False)
    s.setValue("time/auto_detect_tz", True)
    s.setValue("time/use_ntp", True)
    s.setValue("time/use_ntp_local", True)
    s.sync()

    install_translator(app)

    # First-launch server setup (when API base URL is not configured).
    from app.widgets.setup_wizard import ensure_setup_wizard

    if not ensure_setup_wizard():
        app.setQuitOnLastWindowClosed(prev_quit_on_close)
        sys.exit(1)

    # First-run quick-start choices (sign in, create agency, join team).
    try:
        from app.widgets.quick_start_dialog import run_quick_start_flow

        run_quick_start_flow()
    except Exception:
        logger.warning("Quick-start onboarding flow failed; continuing to sign-in.", exc_info=True)

    # Ensure API credentials are set (thin client login)
    from app.widgets.login_dialog import ensure_login

    if not ensure_login(app):
        app.setQuitOnLastWindowClosed(prev_quit_on_close)
        sys.exit(1)

    # Unified startup: cache building + tab preloading with nice splash
    from app.widgets.splash_screen import startup_with_preload

    win = startup_with_preload(app)

    if not win:
        # Startup failed
        app.setQuitOnLastWindowClosed(prev_quit_on_close)
        sys.exit(1)

    # Window is fully ready - show it!
    win.show()
    app.setQuitOnLastWindowClosed(prev_quit_on_close)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
