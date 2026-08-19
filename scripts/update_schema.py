import os
import sys
from pathlib import Path

import django

# Resolve the repository from this script instead of a developer-specific path.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")


def update_schema():
    print("Initializing schema...")
    django.setup()
    from server.pg.schema import ensure_schema

    ensure_schema()
    print("Schema updated successfully.")


if __name__ == "__main__":
    update_schema()
