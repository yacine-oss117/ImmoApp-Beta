from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

RUNTIME_DDL_PATTERNS = (
    re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bCREATE\s+INDEX\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+INDEX\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bCREATE\s+POLICY\b", re.IGNORECASE),
    re.compile(r"\bENABLE\s+ROW\s+LEVEL\s+SECURITY\b", re.IGNORECASE),
    re.compile(r"\bFORCE\s+ROW\s+LEVEL\s+SECURITY\b", re.IGNORECASE),
)

ALLOWLIST = {
    "server/pg/match_partitions.py",
}

MAINTENANCE_SCRIPT_DDL_PATTERNS = (
    re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bCREATE\s+INDEX\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+INDEX\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE),
)


def _runtime_pg_modules() -> list[Path]:
    pg_dir = REPO_ROOT / "server" / "pg"
    files: list[Path] = []
    for path in sorted(pg_dir.rglob("*.py")):
        files.append(path)
    return files


def _maintenance_scripts() -> list[Path]:
    scripts_dir = REPO_ROOT / "scripts" / "maintenance"
    if not scripts_dir.exists():
        return []
    return sorted(scripts_dir.glob("*.py"))


def test_runtime_schema_ddl_is_banned_outside_allowlist() -> None:
    violations: list[str] = []

    for path in _runtime_pg_modules():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in RUNTIME_DDL_PATTERNS:
            if pattern.search(source):
                violations.append(f"{rel}: matched {pattern.pattern}")
                break

    assert not violations, (
        "Runtime schema DDL found outside allowlist. "
        "Move schema ownership to Alembic migrations.\n" + "\n".join(violations)
    )


def test_maintenance_scripts_do_not_mutate_schema() -> None:
    violations: list[str] = []
    for path in _maintenance_scripts():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in MAINTENANCE_SCRIPT_DDL_PATTERNS:
            if pattern.search(source):
                violations.append(f"{rel}: matched {pattern.pattern}")
                break

    assert not violations, (
        "Maintenance scripts must not include manual runtime DDL. "
        "Move changes into Alembic or explicit allowlisted maintenance paths.\n"
        + "\n".join(violations)
    )
