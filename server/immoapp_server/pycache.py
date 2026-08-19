from __future__ import annotations

import os
import sys


def configure_pycache() -> None:
    """Redirect Python bytecode cache into the server appdata root."""
    from core.paths import cache_dir

    pycache_dir = cache_dir() / "pycache"
    try:
        pycache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    os.environ.setdefault("PYTHONPYCACHEPREFIX", str(pycache_dir))
    try:
        sys.pycache_prefix = str(pycache_dir)
    except AttributeError:
        pass
