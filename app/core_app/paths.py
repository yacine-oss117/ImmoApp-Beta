"""
Centralized application paths (client-side).

Defaults:
- Windows: %LOCALAPPDATA%\\ImmoApp (fallback to %APPDATA%)
- Linux/macOS: XDG_DATA_HOME/ImmoApp or ~/.local/share/ImmoApp
"""

from __future__ import annotations

import os
from pathlib import Path

_APP_NAME = "ImmoApp"
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
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not base:
            base = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        return Path(base) / _APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / _APP_NAME
    return Path.home() / ".local" / "share" / _APP_NAME


def media_dir() -> Path:
    """Get the media/object storage directory."""
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
    logs_dir()
    cache_dir()
    media_dir()
    tools_dir()
    tmp_dir()
    backups_dir()
    config_dir()


__all__ = [
    "backups_dir",
    "cache_dir",
    "config_dir",
    "config_path",
    "ensure_appdata_dirs",
    "get_app_data_dir",
    "logs_dir",
    "media_dir",
    "tmp_dir",
    "tools_dir",
]
