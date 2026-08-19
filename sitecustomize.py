"""
Global Python runtime tweaks for the repo to avoid local cache artifacts.
"""

from __future__ import annotations

import os
import sys


def _default_pycache_prefix() -> str:
    root = os.environ.get("IMMOAPP_APPDATA_ROOT")
    if not root:
        if os.name == "nt":
            base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
            root = os.path.join(base, "ImmoApp")
        else:
            xdg = os.environ.get("XDG_DATA_HOME")
            if xdg:
                root = os.path.join(xdg, "ImmoApp")
            else:
                root = os.path.join(os.path.expanduser("~"), ".local", "share", "ImmoApp")
    return os.path.join(root, "cache", "pycache")


_PYCACHE_PREFIX = _default_pycache_prefix()
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("PYTHONPYCACHEPREFIX", _PYCACHE_PREFIX)
sys.dont_write_bytecode = True
if hasattr(sys, "pycache_prefix"):
    sys.pycache_prefix = _PYCACHE_PREFIX
