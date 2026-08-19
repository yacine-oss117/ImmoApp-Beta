"""
Centralized application paths.

Provides consistent path resolution for all runtime data:
- Media/object storage
- Logs
- Cache
- Backups
- Config

Default is server-friendly:
- Windows: %PROGRAMDATA%\\ImmoApp
- Linux/macOS: /var/lib/immoapp (fallback to XDG_DATA_HOME or ~/.local/share)
"""

from __future__ import annotations

import os
from pathlib import Path

# Application name used in path construction
_APP_NAME = "ImmoApp"

# Environment variables for overrides
_ROOT_ENV = "IMMOAPP_APPDATA_ROOT"
_MEDIA_ROOT_ENV = "IMMOAPP_MEDIA_ROOT"


def get_app_data_dir() -> Path:
    """
    Get the root application data directory.
    Default: platform-specific (see module docstring)
    Override via IMMOAPP_APPDATA_ROOT env var.
    """
    env_root = os.environ.get(_ROOT_ENV)
    if env_root:
        return Path(env_root)
    if os.name == "nt":
        base = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        return Path(base) / _APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / _APP_NAME
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return Path("/var/lib") / _APP_NAME.lower()
    return Path.home() / ".local" / "share" / _APP_NAME


def media_dir() -> Path:
    """
    Get the media/object storage directory.
    Override via IMMOAPP_MEDIA_ROOT env var.
    """
    env_media = os.environ.get(_MEDIA_ROOT_ENV)
    if env_media:
        path = Path(env_media)
    else:
        path = get_app_data_dir() / "media"

    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    """Get the logs directory."""
    path = get_app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    """Get the cache directory (thumbnails, temp exports)."""
    path = get_app_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tools_dir() -> Path:
    """Get the tools cache directory (ruff, pytest, mypy)."""
    path = get_app_data_dir() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tmp_dir() -> Path:
    """Get the temporary files directory."""
    path = get_app_data_dir() / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    """Get the backups directory."""
    path = get_app_data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """Get the config directory."""
    path = get_app_data_dir() / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path(name: str = "settings.json") -> Path:
    """Get the full path to a config file."""
    return config_dir() / name


def ensure_appdata_dirs() -> None:
    """Ensure all required AppData directories exist and are writable."""
    # Calling these will trigger mkdir via the getters
    logs_dir()
    cache_dir()
    media_dir()
    tools_dir()
    tmp_dir()
    backups_dir()
    config_dir()
