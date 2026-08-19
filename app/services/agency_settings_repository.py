"""Service orchestrator for agency settings."""

from __future__ import annotations

from app.services.agency_media import (
    flush_pending_media_uploads,
    get_agency_logo_path,
    get_agency_signature_path,
    invalidate_media_cache,
    set_agency_logo,
    set_agency_signature,
)
from app.services.agency_serials import generate_contract_serial
from app.services.agency_settings_cache import (
    get_agency_name,
    get_agency_setting,
    get_all_agency_settings,
    get_audit_actor_name,
    get_contract_serial_prefix,
    set_agency_name,
    set_audit_actor_name,
)
from app.services.agency_settings_cache import (
    set_agency_setting as _set_agency_setting,
)


def set_agency_setting(key: str, value: str) -> None:
    """Set a single agency setting and sync to server."""
    _set_agency_setting(key, value)
    if key == "agency_logo_path":
        invalidate_media_cache("logo")
    if key == "agency_signature_path":
        invalidate_media_cache("signature")


__all__ = [
    "flush_pending_media_uploads",
    "generate_contract_serial",
    "get_agency_logo_path",
    "get_agency_name",
    "get_agency_setting",
    "get_agency_signature_path",
    "get_all_agency_settings",
    "get_audit_actor_name",
    "get_contract_serial_prefix",
    "set_agency_logo",
    "set_agency_name",
    "set_agency_setting",
    "set_agency_signature",
    "set_audit_actor_name",
]
