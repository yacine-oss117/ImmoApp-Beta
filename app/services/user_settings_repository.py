"""Service for user-level settings stored on the API server."""

from __future__ import annotations

from app.services.api_client import api_post_resilient


def set_user_settings(timezone: str | None = None, locale: str | None = None) -> None:
    """Persist user timezone/locale settings to the server."""
    payload: dict[str, str] = {}
    if timezone:
        payload["timezone"] = timezone
    if locale:
        payload["locale"] = locale
    if payload:
        dedupe_parts = sorted(payload.keys())
        api_post_resilient(
            "/settings/user/set",
            payload,
            dedupe_key=f"POST:/settings/user/set:{','.join(dedupe_parts)}",
            label="user_setting.set",
        )
