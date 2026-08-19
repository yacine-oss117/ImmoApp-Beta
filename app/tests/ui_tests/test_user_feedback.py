from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.services.api_client import ApiError
from app.widgets.user_feedback import map_exception_to_user_message

pytestmark = pytest.mark.ui


def test_match_action_api_error_maps_to_friendly_validation_copy() -> None:
    message = map_exception_to_user_message(
        ApiError(409, "duplicate phone"),
        context="match.action.schedule_visit",
    )

    assert message.severity == "warning"
    assert "no longer valid" in message.message.lower()
    assert "refresh" in str(message.action_hint or "").lower()
    assert "duplicate phone" in str(message.technical_detail or "").lower()


def test_crm_refresh_runtime_error_maps_to_workspace_friendly_copy() -> None:
    message = map_exception_to_user_message(
        RuntimeError("database unavailable"),
        context="crm.visits.refresh",
    )

    assert message.severity == "error"
    assert "couldn't load visits" in message.title.lower()
    assert "not available right now" in message.message.lower()
    assert message.technical_detail == "database unavailable"


def test_generic_exception_uses_safe_fallback_copy() -> None:
    message = map_exception_to_user_message(
        Exception("unexpected boom"),
        context="unknown.action",
    )

    assert message.severity == "error"
    assert "couldn't finish" in message.title.lower()
    assert "please try again" in message.message.lower()
    assert message.technical_detail == "unexpected boom"
