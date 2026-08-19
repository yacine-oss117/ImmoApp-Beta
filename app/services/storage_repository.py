"""Storage API helpers for UI actions."""

from __future__ import annotations

from app.services.api_client import ApiError, api_post, as_dict


def delete_storage_object(storage_id: str) -> int:
    """Soft-delete a storage object and return freed bytes (if any)."""
    storage_id = str(storage_id or "").strip()
    if not storage_id:
        raise ValueError("storage_id is required")
    payload = as_dict(api_post("/storage/delete", {"storage_id": storage_id}))
    deleted_raw = payload.get("deleted_bytes", 0)
    if deleted_raw is None:
        return 0
    if isinstance(deleted_raw, (int, float, str)):
        try:
            return int(deleted_raw)
        except ValueError as exc:
            raise ApiError(500, "Invalid storage delete response") from exc
    raise ApiError(500, "Invalid storage delete response")


__all__ = ["delete_storage_object"]
