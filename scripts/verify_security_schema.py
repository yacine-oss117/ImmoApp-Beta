"""
Automated Security Schema Auditor
Queries PostgreSQL catalog to verify RLS state on all tenant-sensitive tables.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from core.env_files import resolve_env_file

_ENV_LOADED = False


def _load_env() -> None:
    """Load environment variables from the configured local env file once."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    repo_root = Path(__file__).resolve().parents[1]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path)
    _ENV_LOADED = True


def audit() -> None:
    print("--- [STARTING SECURITY SCHEMA AUDIT] ---")
    _load_env()
    try:
        from server.pg.schema_security import verify_security_schema
        from server.pg.uow import admin_transaction

        with admin_transaction() as session:
            issues = verify_security_schema(session)
    except Exception as exc:
        print(f"\n[FATAL ERROR] Could not run audit: {exc}")
        sys.exit(1)

    print("\n--- [AUDIT COMPLETE] ---")
    if issues:
        print("RESULT: Security violations found:")
        for issue in issues:
            print(f" - {issue}")
        sys.exit(1)
    print("RESULT: All tenant tables are correctly secured with RLS.")
    sys.exit(0)


if __name__ == "__main__":
    audit()
