"""
Splash screen exports.

Thin wrapper around dedicated splash modules to keep import paths stable.
"""

from __future__ import annotations

from app.widgets.splash_startup import StartupSplash, startup_with_preload

__all__ = [
    "StartupSplash",
    "startup_with_preload",
]
