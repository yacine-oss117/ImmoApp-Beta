from __future__ import annotations

from pathlib import Path

from repo_layout import DOCKERFILE, RESTORE_DRILL_RUNBOOK


def _require(path: str | Path) -> Path:
    p = Path(path)
    if not p.exists():
        raise AssertionError(f"Missing required restore-drill asset: {path}")
    return p


def main() -> None:
    backup_script = _require("scripts/db_backup.ps1")
    restore_script = _require("scripts/db_restore_drill.ps1")
    restore_exec = _require("scripts/verify_restore_drill_execution.py")
    runbook = _require(RESTORE_DRILL_RUNBOOK)
    dockerfile = _require(DOCKERFILE)

    backup_text = backup_script.read_text(encoding="utf-8")
    restore_text = restore_script.read_text(encoding="utf-8")
    restore_exec_text = restore_exec.read_text(encoding="utf-8")
    runbook_text = runbook.read_text(encoding="utf-8")
    dockerfile_text = dockerfile.read_text(encoding="utf-8")

    required_backup_tokens = ("pg_dump", "POSTGRES_ADMIN_USER", "POSTGRES_ADMIN_PASSWORD")
    required_restore_tokens = (
        "pg_restore",
        "verify_security_schema.py",
        "server.api.tests.test_firewall",
    )

    for token in required_backup_tokens:
        if token not in backup_text:
            raise AssertionError(f"db_backup.ps1 missing token: {token}")

    for token in required_restore_tokens:
        if token not in restore_text:
            raise AssertionError(f"db_restore_drill.ps1 missing token: {token}")

    for token in (
        "IMMOAPP_RUN_RESTORE_DRILL",
        "pg_dump",
        "pg_restore",
        "alembic_version",
        "_verify_tenant_smoke",
        "set_config('app.current_agency_id'",
    ):
        if token not in restore_exec_text:
            raise AssertionError(f"verify_restore_drill_execution.py missing token: {token}")

    if "postgresql-client" not in dockerfile_text:
        raise AssertionError(
            "deployment/docker/Dockerfile must include postgresql-client so pg_dump/pg_restore are available in containers."
        )

    if "Run this drill at least monthly" not in runbook_text:
        raise AssertionError("RESTORE_DRILL_RUNBOOK.md must specify monthly drill policy.")
    if "verify_restore_drill_execution.py" not in runbook_text:
        raise AssertionError(
            "RESTORE_DRILL_RUNBOOK.md must include automated restore verification."
        )

    print("verify_restore_drill_assets: OK")


if __name__ == "__main__":
    main()
