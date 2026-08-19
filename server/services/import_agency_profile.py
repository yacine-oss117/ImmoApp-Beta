"""Agency-scoped import profile hints and snapshot maintenance."""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.utils import timezone

from core.data import import_learning_repository
from server.services.import_agency_memory import load_agency_alias_memory
from server.services.import_location_normalizer import shared_location_normalizer

_PROFILE_DOMAINS = ("location", "property_type", "action", "header")


def _entry_wilaya_code(entry: object) -> str:
    metadata = dict(getattr(entry, "metadata", {}) or {})
    wilaya_code = str(metadata.get("wilaya_code", "") or "").strip()
    if wilaya_code:
        return wilaya_code.zfill(2)
    canonical_key = str(getattr(entry, "canonical_key", "") or "").strip()
    canonical_label = str(getattr(entry, "canonical_label", "") or "").strip()
    if canonical_key.isdigit():
        if len(canonical_key) >= 4:
            return canonical_key[:2].zfill(2)
        if len(canonical_key) <= 2:
            return canonical_key.zfill(2)
    if canonical_label:
        result = shared_location_normalizer().normalize(canonical_label)
        extras = dict(result.extracted_extras or {})
        derived = str(extras.get("wilaya_code", "") or "").strip()
        if derived:
            return derived.zfill(2)
    return ""


def load_agency_profile_hints(agency_id: int) -> dict[str, Any]:
    row = import_learning_repository.fetch_agency_profile(agency_id=agency_id)
    if not row:
        return {}
    return {
        "preferred_language": str(row.get("preferred_language", "") or ""),
        "default_wilaya": str(row.get("default_wilaya_code", "") or ""),
        "bundle_shape_hint": str(row.get("common_bundle_shape", "") or ""),
        "property_vocab": dict(row.get("property_vocab") or {}),
        "location_abbreviations": dict(row.get("location_abbreviations") or {}),
        "action_vocab": dict(row.get("action_vocab") or {}),
        "header_vocab": dict(row.get("header_vocab") or {}),
        "common_missing_fields": list(row.get("common_missing_fields") or []),
        "memory_version": str(row.get("memory_version", "") or ""),
    }


def refresh_agency_profile(
    *,
    agency_id: int,
    last_imported_at: object | None = None,
    bundle_shape_hint: str = "",
    preferred_language: str = "",
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    memory = load_agency_alias_memory(agency_id, domains=_PROFILE_DOMAINS)
    location_vocab = {
        key: entry.canonical_label or entry.canonical_key
        for key, entry in memory.trusted.get("location", {}).items()
    }
    property_vocab = {
        key: entry.canonical_label or entry.canonical_key
        for key, entry in memory.trusted.get("property_type", {}).items()
    }
    action_vocab = {
        key: entry.canonical_label or entry.canonical_key
        for key, entry in memory.trusted.get("action", {}).items()
    }
    header_vocab = {
        key: entry.canonical_label or entry.canonical_key
        for key, entry in memory.trusted.get("header", {}).items()
    }

    wilaya_counter: Counter[str] = Counter()
    for entry in memory.trusted.get("location", {}).values():
        wilaya_code = _entry_wilaya_code(entry)
        if wilaya_code:
            wilaya_counter[wilaya_code] += max(1, int(entry.confirm_count or 0))
    default_wilaya_code = wilaya_counter.most_common(1)[0][0] if wilaya_counter else ""

    profile = import_learning_repository.upsert_agency_profile(
        agency_id=agency_id,
        defaults={
            "memory_version": memory.version,
            "preferred_language": preferred_language.strip().lower(),
            "default_wilaya_code": default_wilaya_code,
            "common_bundle_shape": str(bundle_shape_hint or "").strip().lower(),
            "property_vocab": property_vocab,
            "location_abbreviations": location_vocab,
            "action_vocab": action_vocab,
            "header_vocab": header_vocab,
            "common_missing_fields": sorted(
                {str(field) for field in (missing_fields or []) if str(field)}
            ),
            "last_imported_at": last_imported_at or timezone.now(),
        },
    )
    return {
        "agency_id": agency_id,
        "preferred_language": profile.preferred_language,
        "default_wilaya": profile.default_wilaya_code,
        "bundle_shape_hint": profile.common_bundle_shape,
        "memory_version": profile.memory_version,
    }


__all__ = ["load_agency_profile_hints", "refresh_agency_profile"]
