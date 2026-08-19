"""Desktop API helpers for registration and onboarding flows."""

from __future__ import annotations

from typing import cast

from app.services.api_client import api_post, as_dict


def submit_registration(payload: dict[str, object]) -> dict[str, object]:
    response = as_dict(api_post("/auth/register", payload))
    return cast(dict[str, object], response)


def activate_owner(payload: dict[str, object]) -> dict[str, object]:
    response = as_dict(api_post("/auth/activate", payload))
    return cast(dict[str, object], response)


def accept_invite(payload: dict[str, object]) -> dict[str, object]:
    response = as_dict(api_post("/auth/accept-invite", payload))
    return cast(dict[str, object], response)


__all__ = ["accept_invite", "activate_owner", "submit_registration"]
