from __future__ import annotations

import os
from pathlib import Path


def resolve_env_file(repo_root: Path, base_dir: Path) -> Path:
    """Resolve dotenv file path with production-first precedence.

    Precedence:
    1) `DJANGO_ENV_FILE` explicit override
    2) `<IMMOAPP_APPDATA_ROOT>/config/.env.local` (canonical runtime config)
    3) Legacy repo/base fallbacks only when `IMMOAPP_ALLOW_REPO_ENV_FALLBACK=1`

    This keeps runtime deterministic and avoids accidental env drift between
    ProgramData and repository-local files.
    """
    explicit = os.environ.get("DJANGO_ENV_FILE")
    if explicit:
        return Path(explicit)

    appdata_root = os.environ.get("IMMOAPP_APPDATA_ROOT")
    if not appdata_root and os.name == "nt":
        program_data = os.environ.get("PROGRAMDATA")
        if program_data:
            appdata_root = str(Path(program_data) / "ImmoApp")
    appdata_candidate = Path(appdata_root) / "config" / ".env.local" if appdata_root else None
    if appdata_candidate:
        return appdata_candidate

    allow_legacy = os.environ.get("IMMOAPP_ALLOW_REPO_ENV_FALLBACK", "0").strip() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if allow_legacy:
        candidates = (
            repo_root / ".env.local",
            repo_root / ".env",
            base_dir / ".env.local",
            base_dir / ".env",
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate

    # No viable file found: return canonical target path so callers can report/initialize it.
    return base_dir / ".env.local"
