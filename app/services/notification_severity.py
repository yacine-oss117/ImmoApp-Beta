"""Notification event-type to severity mapping."""

from __future__ import annotations


def severity_for_event_type(event_type: str) -> str:
    """Map event type to a stable UI severity."""
    normalized = str(event_type or "").strip().lower()
    if "failed" in normalized or "error" in normalized:
        return "error"
    if "review_required" in normalized:
        return "warning"
    if "approved" in normalized or "completed" in normalized or "joined" in normalized:
        return "success"
    if "alert" in normalized or "warning" in normalized or "expir" in normalized:
        return "warning"
    return "info"


__all__ = ["severity_for_event_type"]
