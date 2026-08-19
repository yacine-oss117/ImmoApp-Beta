"""Deterministic row recovery and recovery provenance for importer ETL."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Mapping

from core.importer.normalize_pipeline import NormalizedRow
from core.importer.normalizers.location_text import extract_location_candidates
from server.services.import_agency_memory import (
    AgencyAliasMemory,
    alias_domain_for_column_type,
    alias_domain_for_field,
    shadow_alias_entry,
    trusted_alias_entry,
)
from server.services.import_constants import ENTITY_TYPE_DEMANDE, ENTITY_TYPE_OFFER
from server.services.import_location_normalizer import shared_location_normalizer
from server.services.import_recoverability import (
    blocking_reasons_for_row,
    classify_row_recoverability,
)
from server.services.import_types import (
    ALIAS_DOMAIN_ACTION,
    ALIAS_DOMAIN_LOCATION,
    ALIAS_DOMAIN_PROPERTY_TYPE,
    RECOVERY_SOURCE_AGENCY_ALIAS_SHADOW,
    RECOVERY_SOURCE_AGENCY_ALIAS_TRUSTED,
    RECOVERY_SOURCE_BUNDLE_CONTEXT,
    RECOVERY_SOURCE_FUZZY_MASTER,
    RECOVERY_SOURCE_LOCATION_CONTEXT,
    RECOVERY_SOURCE_PARENT_CONTEXT,
    RecoveredField,
    RecoveryCandidate,
)

_FUZZY_REVIEW_THRESHOLD = 0.7
_FUZZY_TRUSTED_THRESHOLD = 0.9


def _int_or_none(value: object) -> int | None:
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
            return None
    return None


def _set_wilaya(normalized: NormalizedRow, wilaya_code: int) -> None:
    normalized.data["wilaya"] = int(wilaya_code)
    normalized.data.setdefault("wilaya_id", int(wilaya_code))


def _recover_from_alias(
    normalized: NormalizedRow,
    *,
    field_name: str,
    raw_value: object,
    domain: str,
    memory: AgencyAliasMemory | None,
) -> None:
    current_value = normalized.data.get(field_name)
    trusted = trusted_alias_entry(memory, domain=domain, raw_value=raw_value)
    if trusted is not None:
        recovered_value: object = trusted.canonical_key or trusted.canonical_label
        final_value: object = (
            str(recovered_value)
            if domain in {ALIAS_DOMAIN_ACTION, ALIAS_DOMAIN_PROPERTY_TYPE}
            else recovered_value
        )
        if current_value != final_value:
            normalized.data[field_name] = final_value
            normalized.recovered_fields.append(
                RecoveredField(
                    field=field_name,
                    value=final_value,
                    source=RECOVERY_SOURCE_AGENCY_ALIAS_TRUSTED,
                    confidence=1.0,
                    reason=f"Trusted agency alias recovered {field_name}.",
                    metadata={"canonical_label": trusted.canonical_label},
                ).as_dict()
            )
        if domain == ALIAS_DOMAIN_LOCATION:
            wilaya_code = _int_or_none(trusted.metadata.get("wilaya_code"))
            if wilaya_code and not _int_or_none(normalized.data.get("wilaya")):
                _set_wilaya(normalized, wilaya_code)
                normalized.recovered_fields.append(
                    RecoveredField(
                        field="wilaya",
                        value=wilaya_code,
                        source=RECOVERY_SOURCE_AGENCY_ALIAS_TRUSTED,
                        confidence=1.0,
                        reason=(
                            f"Trusted agency alias for {field_name} implies wilaya "
                            f"{shared_location_normalizer().get_wilaya_name(str(wilaya_code).zfill(2)) or wilaya_code}."
                        ),
                    ).as_dict()
                )
        return

    shadow = shadow_alias_entry(memory, domain=domain, raw_value=raw_value)
    if shadow is not None:
        candidate_value = shadow.canonical_key or shadow.canonical_label
        if current_value == candidate_value:
            return
        normalized.recovery_candidates.append(
            RecoveryCandidate(
                field=field_name,
                candidate_value=candidate_value,
                candidate_label=shadow.canonical_label or shadow.canonical_key,
                confidence=min(0.85, 0.55 + (shadow.confirm_count * 0.1)),
                source=RECOVERY_SOURCE_AGENCY_ALIAS_SHADOW,
                reason=f"Shadow agency alias may recover {field_name}.",
                metadata={"canonical_key": shadow.canonical_key},
            ).as_dict()
        )


def _location_candidates(raw_value: object) -> list[str]:
    text = str(raw_value or "").strip()
    if not text:
        return []
    return extract_location_candidates(text)


def _resolved_location_wilaya_codes(
    *,
    raw_value: object,
    memory: AgencyAliasMemory | None,
) -> tuple[set[int], list[dict[str, Any]]]:
    normalizer = shared_location_normalizer()
    wilaya_codes: set[int] = set()
    recovery_candidates: list[dict[str, Any]] = []
    for candidate in _location_candidates(raw_value):
        trusted = trusted_alias_entry(memory, domain=ALIAS_DOMAIN_LOCATION, raw_value=candidate)
        if trusted is not None:
            alias_wilaya = _int_or_none(trusted.metadata.get("wilaya_code"))
            if alias_wilaya:
                wilaya_codes.add(alias_wilaya)
            continue
        result = normalizer.normalize(candidate)
        extras = dict(result.extracted_extras or {})
        if extras.get("is_wilaya"):
            wilaya_code = _int_or_none(result.value)
            if wilaya_code:
                wilaya_codes.add(wilaya_code)
            continue
        wilaya_code = _int_or_none(extras.get("wilaya_code"))
        if wilaya_code is None:
            raw_code = str(result.value or "").strip()
            if raw_code.isdigit() and len(raw_code) >= 5:
                wilaya_code = _int_or_none(raw_code[:2])
        if wilaya_code:
            wilaya_codes.add(wilaya_code)
        if _FUZZY_REVIEW_THRESHOLD <= result.confidence < _FUZZY_TRUSTED_THRESHOLD:
            label = str(
                extras.get("matched_name") or normalizer.get_commune_name(str(result.value)) or ""
            )
            recovery_candidates.append(
                RecoveryCandidate(
                    field="location",
                    candidate_value=result.value,
                    candidate_label=label or str(result.value),
                    confidence=float(result.confidence),
                    source=RECOVERY_SOURCE_FUZZY_MASTER,
                    reason="Fuzzy location match needs review confirmation.",
                    metadata={"wilaya_code": wilaya_code or 0},
                ).as_dict()
            )
    return wilaya_codes, recovery_candidates


def _recover_location_context(
    normalized: NormalizedRow,
    *,
    raw_row: Mapping[str, Any],
    column_types: Mapping[str, str],
    entity_type: str,
    memory: AgencyAliasMemory | None,
) -> None:
    if _int_or_none(normalized.data.get("wilaya")):
        return

    collected_wilayas: set[int] = set()
    for field_name, column_type in column_types.items():
        if str(column_type) != "location":
            continue
        raw_value = raw_row.get(field_name)
        if raw_value in {None, ""}:
            continue
        candidate_wilayas, recovery_candidates = _resolved_location_wilaya_codes(
            raw_value=raw_value,
            memory=memory,
        )
        collected_wilayas.update(candidate_wilayas)
        normalized.recovery_candidates.extend(recovery_candidates)

    if len(collected_wilayas) == 1:
        wilaya_code = next(iter(collected_wilayas))
        _set_wilaya(normalized, wilaya_code)
        normalized.recovered_fields.append(
            RecoveredField(
                field="wilaya",
                value=wilaya_code,
                source=RECOVERY_SOURCE_LOCATION_CONTEXT,
                confidence=1.0,
                reason=("Recovered wilaya from normalized location context."),
                metadata={
                    "wilaya_label": shared_location_normalizer().get_wilaya_name(
                        str(wilaya_code).zfill(2)
                    )
                    or str(wilaya_code)
                },
            ).as_dict()
        )
        return

    if len(collected_wilayas) > 1:
        normalized.blocking_reasons.append(
            "Location candidates span multiple wilayas and need human review."
        )
    elif (
        entity_type in {ENTITY_TYPE_DEMANDE, ENTITY_TYPE_OFFER}
        and not normalized.recovery_candidates
    ):
        normalized.blocking_reasons.append("Unable to recover wilaya from location context.")


def _recover_parent_context(
    normalized: NormalizedRow,
    *,
    parent_context: Mapping[str, Any] | None,
    source: str,
) -> None:
    if parent_context is None or _int_or_none(normalized.data.get("wilaya")):
        return
    parent_wilaya = _int_or_none(parent_context.get("wilaya") or parent_context.get("wilaya_id"))
    if parent_wilaya is None:
        return
    _set_wilaya(normalized, parent_wilaya)
    normalized.recovered_fields.append(
        RecoveredField(
            field="wilaya",
            value=parent_wilaya,
            source=source,
            confidence=0.9,
            reason="Recovered wilaya from compatible parent/bundle context.",
        ).as_dict()
    )


def _review_field_names(normalized: NormalizedRow) -> set[str]:
    return {
        str(getattr(item, "field_name", "") or "").strip()
        for item in list(normalized.review_fields or [])
        if str(getattr(item, "field_name", "") or "").strip()
    }


def _has_raw_value(raw_row: Mapping[str, Any], field_name: str) -> bool:
    value = raw_row.get(field_name)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _materialize_demande_preference_defaults(
    normalized: NormalizedRow,
    *,
    raw_row: Mapping[str, Any],
) -> None:
    review_fields = _review_field_names(normalized)
    if (
        normalized.data.get("budget_max") is not None
        and normalized.data.get("budget_min") is None
        and "budget_max" not in review_fields
        and "budget_min" not in review_fields
    ):
        normalized.data["budget_min"] = 0.0
        normalized.recovered_fields.append(
            RecoveredField(
                field="budget_min",
                value=0.0,
                source=RECOVERY_SOURCE_BUNDLE_CONTEXT,
                confidence=0.95,
                reason="Single budget value was interpreted as a maximum preference.",
            ).as_dict()
        )
    elif (
        normalized.data.get("budget_min") is not None
        and normalized.data.get("budget_max") is None
        and "budget_min" not in review_fields
        and "budget_max" not in review_fields
    ):
        normalized.data["budget_max"] = normalized.data.get("budget_min")
        normalized.recovered_fields.append(
            RecoveredField(
                field="budget_max",
                value=normalized.data.get("budget_min"),
                source=RECOVERY_SOURCE_BUNDLE_CONTEXT,
                confidence=0.9,
                reason="Single budget bound was mirrored so the demande range stays usable.",
            ).as_dict()
        )

    if (
        normalized.data.get("surface_min") is not None
        and normalized.data.get("surface_max") is None
        and "surface_min" not in review_fields
        and "surface_max" not in review_fields
    ):
        normalized.data["surface_max"] = normalized.data.get("surface_min")
        normalized.recovered_fields.append(
            RecoveredField(
                field="surface_max",
                value=normalized.data.get("surface_min"),
                source=RECOVERY_SOURCE_BUNDLE_CONTEXT,
                confidence=0.95,
                reason="Single surface value was treated as an exact preference.",
            ).as_dict()
        )
    elif (
        normalized.data.get("surface_max") is not None
        and normalized.data.get("surface_min") is None
        and "surface_min" not in review_fields
        and "surface_max" not in review_fields
    ):
        normalized.data["surface_min"] = normalized.data.get("surface_max")
        normalized.recovered_fields.append(
            RecoveredField(
                field="surface_min",
                value=normalized.data.get("surface_max"),
                source=RECOVERY_SOURCE_BUNDLE_CONTEXT,
                confidence=0.95,
                reason="Single surface value was treated as an exact preference.",
            ).as_dict()
        )

    if (
        normalized.data.get("beds_min") is None
        and "beds_min" not in review_fields
        and not _has_raw_value(raw_row, "beds_min")
    ):
        normalized.data["beds_min"] = 0
        normalized.recovered_fields.append(
            RecoveredField(
                field="beds_min",
                value=0,
                source=RECOVERY_SOURCE_BUNDLE_CONTEXT,
                confidence=0.8,
                reason="Missing bedroom preference defaulted to no minimum.",
            ).as_dict()
        )


def apply_row_recovery(
    *,
    normalized: NormalizedRow,
    raw_row: Mapping[str, Any],
    entity_type: str,
    column_types: Mapping[str, str],
    memory: AgencyAliasMemory | None = None,
    parent_context: Mapping[str, Any] | None = None,
    bundle_context: Mapping[str, Any] | None = None,
    deferred_required_fields: Iterable[str] | None = None,
) -> NormalizedRow:
    for field_name, raw_value in raw_row.items():
        domain = alias_domain_for_column_type(
            str(column_types.get(field_name, ""))
        ) or alias_domain_for_field(field_name)
        if domain is None:
            continue
        _recover_from_alias(
            normalized,
            field_name=field_name,
            raw_value=raw_value,
            domain=domain,
            memory=memory,
        )

    _recover_location_context(
        normalized,
        raw_row=raw_row,
        column_types=column_types,
        entity_type=entity_type,
        memory=memory,
    )
    if parent_context is not None:
        _recover_parent_context(
            normalized,
            parent_context=parent_context,
            source=RECOVERY_SOURCE_PARENT_CONTEXT,
        )
    if bundle_context is not None:
        _recover_parent_context(
            normalized,
            parent_context=bundle_context,
            source=RECOVERY_SOURCE_BUNDLE_CONTEXT,
        )
    if entity_type == ENTITY_TYPE_DEMANDE:
        _materialize_demande_preference_defaults(
            normalized,
            raw_row=raw_row,
        )

    normalized.blocking_reasons = blocking_reasons_for_row(
        normalized,
        entity_type=entity_type,
        deferred_required_fields=deferred_required_fields,
    )
    normalized.recoverability_class = classify_row_recoverability(
        normalized,
        entity_type=entity_type,
        deferred_required_fields=deferred_required_fields,
    )
    if normalized.recoverability_class != "auto_recoverable":
        normalized.needs_review = True
    if normalized.blocking_reasons:
        normalized.remarks.extend(
            reason for reason in normalized.blocking_reasons if reason not in normalized.remarks
        )
    return normalized


__all__ = ["apply_row_recovery"]
