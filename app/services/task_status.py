"""
Task status helpers for background jobs.
"""

from __future__ import annotations

from app.services.api_client import api_get, as_dict


def get_task_status(task_id: str) -> dict[str, object]:
    """Fetch task status/result from the server."""
    response = api_get(f"/tasks/{task_id}")
    return as_dict(response)
