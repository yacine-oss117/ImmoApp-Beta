"""Agency-scoped alias memory for importer intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from core.data import import_learning_repository
from core.importer.normalizers.location_text import normalize_text
from server.imports.models import ImportAgencyAlias
from server.services.import_types import (
    ALIAS_DOMAIN_ACTION,
    ALIAS_DOMAIN_LOCATION,
    ALIAS_DOMAIN_PRICE,
    ALIAS_DOMAIN_PROPERTY_TYPE,
)

_CACHE: dict[tuple[int, str, tuple[str, ...]], AgencyAliasMemory] = {}

_DOMAIN_BY_COLUMN_TYPE: dict[str, str] = {
    "location": ALIAS_DOMAIN_LOCATION,
    "type": ALIAS_DOMAIN_PROPERTY_TYPE,
    "action": ALIAS_DOMAIN_ACTION,
    "price": ALIAS_DOMAIN_PRICE,
}

_DOMAIN_BY_FIELD: dict[str, str] = {
    "location": ALIAS_DOMAIN_LOCATION,
    "locations": ALIAS_DOMAIN_LOCATION,
    "wilaya": ALIAS_DOMAIN_LOCATION,
    "type": ALIAS_DOMAIN_PROPERTY_TYPE,
    "action": ALIAS_DOMAIN_ACTION,
    "budget": ALIAS_DOMAIN_PRICE,
    "budget_min": ALIAS_DOMAIN_PRICE,
    "budget_max": ALIAS_DOMAIN_PRICE,
    "price": ALIAS_DOMAIN_PRICE,
}


def _strip_accents(text: str) -> str:
    replacements = {
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "à": "a",
        "â": "a",
        "ä": "a",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ö": "o",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ç": "c",
        "'": "",
        "_": " ",
        "-": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return " ".join(text.split())


def normalize_alias_value(domain: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if domain == ALIAS_DOMAIN_LOCATION:
        return normalize_text(text)
    if domain == ALIAS_DOMAIN_PRICE:
        return _strip_accents(text.lower()).replace("\xa0", "").replace(" ", "").replace(",", ".")
    return _strip_accents(text.lower())


def alias_domain_for_column_type(column_type: str) -> str | None:
    return _DOMAIN_BY_COLUMN_TYPE.get(str(column_type or "").strip().lower())


def alias_domain_for_field(field_name: str) -> str | None:
    return _DOMAIN_BY_FIELD.get(str(field_name or "").strip().lower())


@dataclass(frozen=True)
class AgencyAliasEntry:
    agency_id: int
    domain: str
    source_value_original: str
    source_value_normalized: str
    canonical_key: str
    canonical_label: str
    state: str
    confirm_count: int
    reject_count: int
    distinct_job_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgencyAliasMemory:
    agency_id: int
    version: str
    trusted: dict[str, dict[str, AgencyAliasEntry]] = field(default_factory=dict)
    shadow: dict[str, dict[str, AgencyAliasEntry]] = field(default_factory=dict)


def _memory_version(agency_id: int, domains: tuple[str, ...]) -> str:
    return import_learning_repository.alias_memory_version(
        agency_id=agency_id,
        domains=domains,
    )


def load_agency_alias_memory(
    agency_id: int,
    *,
    domains: Iterable[str] | None = None,
) -> AgencyAliasMemory:
    normalized_domains = tuple(sorted({str(domain) for domain in (domains or []) if str(domain)}))
    version = _memory_version(agency_id, normalized_domains)
    cache_key = (agency_id, version, normalized_domains)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    trusted: dict[str, dict[str, AgencyAliasEntry]] = {}
    shadow: dict[str, dict[str, AgencyAliasEntry]] = {}
    for row in import_learning_repository.fetch_alias_rows(
        agency_id=agency_id,
        domains=normalized_domains,
    ):
        entry = AgencyAliasEntry(
            agency_id=int(row.get("agency_id", 0) or 0),
            domain=str(row.get("domain", "") or ""),
            source_value_original=str(row.get("source_value_original", "") or ""),
            source_value_normalized=str(row.get("source_value_normalized", "") or ""),
            canonical_key=str(row.get("canonical_key", "") or ""),
            canonical_label=str(row.get("canonical_label", "") or ""),
            state=str(row.get("state", "") or ""),
            confirm_count=int(row.get("confirm_count", 0) or 0),
            reject_count=int(row.get("reject_count", 0) or 0),
            distinct_job_count=int(row.get("distinct_job_count", 0) or 0),
            metadata=dict(row.get("metadata") or {}),
        )
        row_state = str(row.get("state", "") or "")
        target = trusted if row_state == ImportAgencyAlias.State.TRUSTED else shadow
        if row_state == ImportAgencyAlias.State.REJECTED:
            continue
        target.setdefault(entry.domain, {})[entry.source_value_normalized] = entry

    memory = AgencyAliasMemory(
        agency_id=agency_id,
        version=version,
        trusted=trusted,
        shadow=shadow,
    )
    _CACHE[cache_key] = memory
    return memory


def invalidate_agency_alias_memory(agency_id: int) -> None:
    for key in list(_CACHE.keys()):
        if key[0] == agency_id:
            _CACHE.pop(key, None)


def trusted_alias_entry(
    memory: AgencyAliasMemory | None,
    *,
    domain: str,
    raw_value: object,
) -> AgencyAliasEntry | None:
    if memory is None:
        return None
    normalized = normalize_alias_value(domain, raw_value)
    if not normalized:
        return None
    return memory.trusted.get(domain, {}).get(normalized)


def shadow_alias_entry(
    memory: AgencyAliasMemory | None,
    *,
    domain: str,
    raw_value: object,
) -> AgencyAliasEntry | None:
    if memory is None:
        return None
    normalized = normalize_alias_value(domain, raw_value)
    if not normalized:
        return None
    return memory.shadow.get(domain, {}).get(normalized)


__all__ = [
    "AgencyAliasEntry",
    "AgencyAliasMemory",
    "alias_domain_for_column_type",
    "alias_domain_for_field",
    "invalidate_agency_alias_memory",
    "load_agency_alias_memory",
    "normalize_alias_value",
    "shadow_alias_entry",
    "trusted_alias_entry",
]
