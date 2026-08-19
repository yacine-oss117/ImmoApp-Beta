"""
Location master-data loader.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

# Path to master data
MASTER_DATA_DIR = Path(__file__).parent.parent / "master_data"


@lru_cache(maxsize=1)
def load_wilayas() -> dict[str, Any]:
    """Load wilayas master data (cached)."""
    path = MASTER_DATA_DIR / "wilayas.json"
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


@lru_cache(maxsize=1)
def load_communes() -> dict[str, Any]:
    """Load communes master data (cached)."""
    path = MASTER_DATA_DIR / "communes.json"
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


@lru_cache(maxsize=1)
def load_aliases() -> dict[str, str]:
    """Load location aliases (cached)."""
    path = MASTER_DATA_DIR / "aliases.json"
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        data.pop("_comment", None)
        return cast(dict[str, str], data)
