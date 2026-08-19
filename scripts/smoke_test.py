import os
import sys
import traceback

# Ensure headless-safe UI and lightweight startup.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IMMOAPP_STARTUP_LIGHT", "1")
os.environ.setdefault("IMMOAPP_OFFLINE", "1")
os.environ.setdefault("IMMOAPP_SKIP_SCHEMA_INIT", "1")

# Setup paths
sys.path.append(os.path.join(os.getcwd(), "server"))
sys.path.append(os.getcwd())

# Mock Django setup to avoid full DB requirement if possible, or just use what we have
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
import django

try:
    django.setup()
    print("[PASS] Django setup complete")
except Exception:
    traceback.print_exc()
    print("[FAIL] Django setup failed")
    sys.exit(1)

from PySide6.QtWidgets import QApplication

from app.widgets.login_dialog import LoginDialog
from server.pg import uow as pg_uow


def smoke_test() -> None:
    print("Starting client smoke test...")

    # 1. Initialize QApplication
    try:
        _app = QApplication.instance() or QApplication(sys.argv)
        print("[PASS] QApplication initialized")
    except Exception:
        traceback.print_exc()
        print("[FAIL] QApplication init failed")
        sys.exit(1)

    # 2. Try to instantiate LoginDialog
    print("Attempting to create LoginDialog...")
    try:
        # We need a dummy usage of LoginDialog to see if it imports and inits
        # We won't exec() it because that blocks.
        _dlg = LoginDialog()
        print("[PASS] LoginDialog instantiated successfully")
    except Exception:
        traceback.print_exc()
        print("[FAIL] LoginDialog instantiation failed")
        sys.exit(1)
    finally:
        try:
            pg_uow.close_pool()
        except Exception:
            pass

    print("Smoke test passed!")


def main() -> None:
    smoke_test()


if __name__ == "__main__":
    main()
