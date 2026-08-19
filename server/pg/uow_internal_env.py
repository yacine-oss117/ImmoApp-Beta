"""Environment helpers for Postgres UoW plumbing."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from core.env_files import resolve_env_file

_ENV_LOADED = False


def _load_env() -> None:
    """Load environment variables from the configured local env file once."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    repo_root = Path(__file__).resolve().parents[2]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path)
    _ENV_LOADED = True


def _require_env(name: str) -> str:
    """Return a required environment variable or raise."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required to connect to Postgres")
    return value


__all__ = ["_load_env", "_require_env"]
