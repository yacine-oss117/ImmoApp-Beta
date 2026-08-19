"""Structured review-learning pipeline for importer corrections."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.data import import_learning_repository
from server.imports.models import ImportAgencyAlias, ImportCorrectionSignal
from server.services.import_agency_memory import (
    alias_domain_for_field,
    invalidate_agency_alias_memory,
    normalize_alias_value,
)
from server.services.import_location_normalizer import shared_location_normalizer

_SUPPORTED_DOMAINS = {"location", "property_type", "action", "price"}
_PROMOTE_CONFIRM_COUNT = 3
_PROMOTE_DISTINCT_JOB_COUNT = 2
_DEMOTE_REJECT_COUNT = 2


@dataclass(frozen=True)
class ExtractedCorrectionSignals:
    signals: list[ImportCorrectionSignal]
    price_metadata_by_signal_id: dict[int, dict[str, object]]


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _meaningfully_differs(domain: str, before: object, after: object) -> bool:
    return normalize_alias_value(domain, before) != normalize_alias_value(domain, after)


def _canonical_location_label(value: object) -> tuple[str, str]:
    text = _stringify(value).strip()
    if not text:
        return "", ""
    normalizer = shared_location_normalizer()
    result = normalizer.normalize(text)
    extras = dict(result.extracted_extras or {})
    if extras.get("is_wilaya"):
        label = normalizer.get_wilaya_name(text.zfill(2)) or text
        return text, label
    if text.isdigit() and len(text) >= 4:
        label = normalizer.get_commune_name(text) or text
        return text, label
    matched_name = str(extras.get("matched_name", "") or "")
    return text, matched_name or text


def _location_metadata(value: object) -> dict[str, object]:
    text = _stringify(value).strip()
    if not text:
        return {}
    normalizer = shared_location_normalizer()
    result = normalizer.normalize(text)
    extras = dict(result.extracted_extras or {})
    wilaya_code = extras.get("wilaya_code")
    raw_code = extras.get("code")
    if (
        wilaya_code in (None, "")
        and isinstance(raw_code, str)
        and raw_code.isdigit()
        and len(raw_code) >= 2
    ):
        wilaya_code = raw_code[:2]
    metadata: dict[str, object] = {}
    if wilaya_code not in (None, ""):
        try:
            metadata["wilaya_code"] = int(str(wilaya_code))
        except (TypeError, ValueError):
            metadata["wilaya_code"] = str(wilaya_code)
    if raw_code not in (None, ""):
        metadata["code"] = str(raw_code)
    matched_name = str(extras.get("matched_name", "") or "").strip()
    if matched_name:
        metadata["matched_name"] = matched_name
    return metadata


def _canonical_value(domain: str, value: object) -> tuple[str, str]:
    if domain == "location":
        return _canonical_location_label(value)
    if domain == "price":
        if isinstance(value, bool):
            value = int(value)
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric.is_integer():
                text = str(int(numeric))
            else:
                text = str(numeric)
            return text, text
    text = _stringify(value).strip()
    return text, text


def _review_field_lookup(review_entry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    review_fields = list(review_entry.get("review_fields", []) or [])
    lookup: dict[str, dict[str, Any]] = {}
    for field in review_fields:
        if not isinstance(field, Mapping):
            continue
        field_name = str(field.get("field", "") or "").strip()
        if field_name:
            lookup[field_name] = {str(key): value for key, value in field.items()}
    return lookup


def _price_learning_metadata(
    *,
    review_entry: Mapping[str, Any],
    field_name: str,
    corrected_value: object,
) -> dict[str, object]:
    review_field = _review_field_lookup(review_entry).get(field_name, {})
    metadata = dict(review_field.get("metadata") or {})
    candidates = list(metadata.get("interpretation_candidates", []) or [])
    selected: dict[str, Any] = {}
    corrected_text = _stringify(corrected_value).strip()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        normalized_dzd = candidate.get("normalized_dzd")
        candidate_text = _stringify(normalized_dzd).strip()
        if candidate_text == corrected_text:
            selected = {str(key): value for key, value in candidate.items()}
            break
    if not selected and candidates:
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            if bool(candidate.get("selected_by_context", False)):
                selected = {str(key): value for key, value in candidate.items()}
                break

    learned: dict[str, object] = {}
    if selected:
        for key in ("dialect", "expression_kind"):
            value = str(selected.get(key, "") or "").strip()
            if value:
                learned[key] = value
    header_context = str(metadata.get("source_header", "") or "").strip()
    if header_context:
        learned["header_context"] = header_context
    normalized_data = dict(review_entry.get("normalized_data", {}) or {})
    action_context = str(normalized_data.get("action", "") or "").strip()
    if action_context:
        learned["action_context"] = action_context
    file_model_hint = str(review_entry.get("file_model_hint", "") or "").strip()
    if file_model_hint:
        learned["file_model_hint"] = file_model_hint
    return learned


def _learning_eligible_action(action: object) -> bool:
    normalized = str(action or "").strip().lower()
    return normalized in {"create", "update", "create_new", "update_existing"}


def _extract_signal_rows(
    *,
    applied_rows: Iterable[Mapping[str, Any]],
    agency_id: int,
    job_id: str,
    actor_id: int,
) -> ExtractedCorrectionSignals:
    signals: list[ImportCorrectionSignal] = []
    price_metadata_by_signal_id: dict[int, dict[str, object]] = {}
    created_at = timezone.now()
    for applied in applied_rows:
        action = str(applied.get("action", "") or "").strip().lower()
        if not _learning_eligible_action(action):
            continue
        correction_payload = dict(applied.get("correction_payload", {}) or {})
        if not correction_payload:
            continue
        review_entry = dict(applied.get("review_entry", {}) or {})
        source_row = dict(review_entry.get("normalized_data") or review_entry.get("data") or {})
        entity_type = str(applied.get("entity_type", "") or "")
        validated_row = dict(applied.get("validated_row", {}) or {})
        review_field_lookup = _review_field_lookup(review_entry)
        for field_name, corrected_value in correction_payload.items():
            domain = alias_domain_for_field(str(field_name))
            if domain not in _SUPPORTED_DOMAINS:
                continue
            before_value = source_row.get(field_name)
            if domain == "price":
                review_field = review_field_lookup.get(str(field_name), {})
                if review_field:
                    before_value = review_field.get("original", before_value)
            after_value = validated_row.get(field_name, corrected_value)
            if not _meaningfully_differs(domain, before_value, after_value):
                continue
            source_value_normalized = normalize_alias_value(domain, before_value)
            corrected_value_normalized = normalize_alias_value(domain, after_value)
            if not corrected_value_normalized:
                continue
            canonical_key, canonical_label = _canonical_value(domain, after_value)
            signals.append(
                ImportCorrectionSignal(
                    agency_id=agency_id,
                    job_id=job_id,
                    actor_id=actor_id,
                    row_ordinal=int(applied.get("row_num", 0) or 0),
                    entity_type=entity_type,
                    field_name=str(field_name),
                    domain=domain,
                    source_value_original=_stringify(before_value),
                    source_value_normalized=source_value_normalized,
                    corrected_value_original=_stringify(after_value),
                    corrected_value_normalized=corrected_value_normalized,
                    canonical_key=canonical_key,
                    canonical_label=canonical_label,
                    decision_action=action,
                    created_at=created_at,
                )
            )
            if domain == "price":
                price_metadata_by_signal_id[id(signals[-1])] = _price_learning_metadata(
                    review_entry=review_entry,
                    field_name=str(field_name),
                    corrected_value=after_value,
                )
    return ExtractedCorrectionSignals(
        signals=signals,
        price_metadata_by_signal_id=price_metadata_by_signal_id,
    )


def _promote_or_demote_alias(row: ImportAgencyAlias) -> bool:
    promoted = False
    if (
        row.state == ImportAgencyAlias.State.SHADOW
        and row.confirm_count >= _PROMOTE_CONFIRM_COUNT
        and row.distinct_job_count >= _PROMOTE_DISTINCT_JOB_COUNT
        and row.reject_count < 2
    ):
        row.state = ImportAgencyAlias.State.TRUSTED
        row.promoted_at = timezone.now()
        promoted = True
    elif row.state == ImportAgencyAlias.State.TRUSTED and row.reject_count >= _DEMOTE_REJECT_COUNT:
        row.state = ImportAgencyAlias.State.SHADOW
        row.promoted_at = None
    return promoted


def _apply_signal_aggregates(
    *,
    agency_id: int,
    actor_id: int,
    job_id: str,
    signals: Iterable[ImportCorrectionSignal],
    price_metadata_by_signal_id: Mapping[int, dict[str, object]],
) -> int:
    promotions_applied = 0
    grouped: dict[tuple[str, str], list[ImportCorrectionSignal]] = defaultdict(list)
    for signal in signals:
        grouped[(signal.domain, signal.source_value_normalized)].append(signal)

    now = timezone.now()
    for (domain, source_value_normalized), grouped_signals in grouped.items():
        latest_signal = grouped_signals[-1]
        alias, _created = import_learning_repository.get_or_create_agency_alias(
            agency_id=agency_id,
            domain=domain,
            source_value_normalized=source_value_normalized,
            defaults={
                "source_value_original": latest_signal.source_value_original,
                "canonical_key": latest_signal.canonical_key,
                "canonical_label": latest_signal.canonical_label,
                "state": ImportAgencyAlias.State.SHADOW,
                "confirm_count": 0,
                "reject_count": 0,
                "distinct_job_count": 1,
                "first_seen_at": now,
                "last_seen_at": now,
                "last_job_id": job_id,
                "last_actor_id": actor_id,
                "metadata": (
                    _location_metadata(latest_signal.corrected_value_original)
                    if domain == "location"
                    else (
                        dict(price_metadata_by_signal_id.get(id(latest_signal), {}) or {})
                        if domain == "price"
                        else {}
                    )
                ),
            },
        )
        for signal in grouped_signals:
            alias.source_value_original = (
                signal.source_value_original or alias.source_value_original
            )
            if (
                alias.canonical_key
                and alias.canonical_key != signal.canonical_key
                and alias.confirm_count >= 2
            ):
                alias.reject_count += 1
            else:
                alias.canonical_key = signal.canonical_key
                alias.canonical_label = signal.canonical_label
                alias.confirm_count += 1
            if domain == "location":
                metadata = dict(alias.metadata or {})
                metadata.update(_location_metadata(signal.corrected_value_original))
                alias.metadata = metadata
            elif domain == "price":
                metadata = dict(alias.metadata or {})
                metadata.update(dict(price_metadata_by_signal_id.get(id(signal), {}) or {}))
                alias.metadata = metadata
            if str(getattr(alias, "last_job_id", "") or "") != str(job_id):
                alias.distinct_job_count += 1
            alias.last_seen_at = signal.created_at
            alias.last_job_id = job_id
            alias.last_actor_id = actor_id
        if _promote_or_demote_alias(alias):
            promotions_applied += 1
        import_learning_repository.save_agency_alias(
            alias,
            update_fields=[
                "source_value_original",
                "canonical_key",
                "canonical_label",
                "state",
                "confirm_count",
                "reject_count",
                "distinct_job_count",
                "promoted_at",
                "last_seen_at",
                "last_job_id",
                "last_actor_id",
                "metadata",
            ],
        )
    return promotions_applied


def record_learning_signals(
    *,
    agency_id: int,
    job_id: str,
    actor_id: int,
    applied_rows: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    with transaction.atomic():
        extracted = _extract_signal_rows(
            applied_rows=applied_rows,
            agency_id=agency_id,
            job_id=job_id,
            actor_id=actor_id,
        )
        signals = extracted.signals
        if not signals:
            return {"signals_recorded": 0, "promotions_applied": 0}
        import_learning_repository.bulk_create_correction_signals(signals)
        promotions_applied = _apply_signal_aggregates(
            agency_id=agency_id,
            actor_id=actor_id,
            job_id=job_id,
            signals=signals,
            price_metadata_by_signal_id=extracted.price_metadata_by_signal_id,
        )
    invalidate_agency_alias_memory(agency_id)
    return {"signals_recorded": len(signals), "promotions_applied": promotions_applied}


__all__ = ["record_learning_signals"]
