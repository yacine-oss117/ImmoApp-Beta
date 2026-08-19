"""Build identity helpers for desktop diagnostics and packaged builds."""

from __future__ import annotations

import json
import os
from importlib import resources


def _load_packaged_identity() -> dict[str, object]:
    try:
        resource = resources.files("app").joinpath("build_identity.json")
        if not resource.is_file():
            return {}
        data = json.loads(resource.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_build_identity() -> dict[str, object]:
    """Return non-secret version/build identity for support diagnostics."""

    packaged = _load_packaged_identity()
    version = str(
        os.environ.get("IMMOAPP_CLIENT_VERSION") or packaged.get("version") or "desktop"
    ).strip()
    git_sha = str(os.environ.get("IMMOAPP_BUILD_GIT_SHA") or packaged.get("git_sha") or "").strip()
    build_time = str(
        os.environ.get("IMMOAPP_BUILD_TIME_UTC") or packaged.get("build_time_utc") or ""
    ).strip()
    source = str(packaged.get("source") or "runtime").strip()
    return {
        "version": version or "desktop",
        "git_sha": git_sha,
        "build_time_utc": build_time,
        "source": source,
    }


__all__ = ["get_build_identity"]
