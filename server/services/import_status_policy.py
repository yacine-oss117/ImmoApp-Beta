"""Queue-depth and polling policy helpers for importer status projection."""

from __future__ import annotations

from collections.abc import Mapping

from core.runtime.hub_runtime_profile import resolve_hub_runtime_profile
from server.imports.models import ImportJob
from server.services.import_job_queue import agency_queue_depth


def optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def coerce_progress_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def coerce_summary_mapping(value: object, *, allowed_keys: set[str]) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        key_text = str(key)
        if key_text not in allowed_keys:
            continue
        if isinstance(item, (int, float)):
            result[key_text] = int(item)
    return result


def status_poll_after_ms(
    *,
    public_status: str,
    public_stage: str,
    progress_detail: Mapping[str, object],
    row_count: int,
) -> int:
    normalized_status = str(public_status or "").strip().lower()
    profile_poll_ms = int(
        resolve_hub_runtime_profile().effective_limits().polling_interval_seconds * 1000
    )
    normalized_stage = str(public_stage or "").strip().lower()
    if normalized_status in {"completed", "failed", "review"}:
        return 0
    if normalized_status == "queued":
        return max(1000, profile_poll_ms)
    if normalized_stage in {"upload", "mapping"} or normalized_status in {"pending", "parsing"}:
        return max(150, min(profile_poll_ms, 1000))
    phase = (
        str(progress_detail.get("phase", normalized_stage or "executing") or "executing")
        .strip()
        .lower()
    )
    if phase == "rebuild":
        return max(500, min(profile_poll_ms, 1000))
    rows_total = max(
        0,
        coerce_progress_int(progress_detail.get("rows_total"), default=0),
        int(row_count or 0),
    )
    if rows_total <= 500:
        return max(150, min(profile_poll_ms, 1000))
    if rows_total <= 2000:
        return max(250, min(profile_poll_ms, 1000))
    return max(500, min(profile_poll_ms, 1000))


def queue_poll_after_ms(*, claim_status: str) -> int:
    profile_poll_ms = int(
        resolve_hub_runtime_profile().effective_limits().polling_interval_seconds * 1000
    )
    return (
        max(1000, profile_poll_ms)
        if str(claim_status or "").strip().lower() == "queued"
        else max(150, min(profile_poll_ms, 1000))
    )


def cached_agency_queue_depth(workflow: Mapping[str, object], session_status: str) -> int | None:
    if str(session_status or "").strip().lower() != "queued":
        return 0
    cached = workflow.get("agency_queue_depth")
    if isinstance(cached, bool):
        return int(cached)
    if isinstance(cached, int):
        return max(0, cached)
    if isinstance(cached, float):
        return max(0, int(cached))
    return None


def live_agency_queue_depth(*, agency_id: int, session_status: str) -> int:
    if session_status != ImportJob.Status.QUEUED:
        return 0
    return agency_queue_depth(agency_id=int(agency_id or 0))


__all__ = [
    "cached_agency_queue_depth",
    "coerce_progress_int",
    "coerce_summary_mapping",
    "live_agency_queue_depth",
    "optional_int",
    "queue_poll_after_ms",
    "status_poll_after_ms",
]
