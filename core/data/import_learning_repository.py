from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from server.imports.models import (
    ImportAgencyAlias,
    ImportAgencyProfile,
    ImportCorrectionSignal,
    ImportDeadLetterRow,
    ImportJob,
)


def alias_memory_version(*, agency_id: int, domains: tuple[str, ...]) -> str:
    queryset = ImportAgencyAlias.objects.filter(agency_id=agency_id)
    if domains:
        queryset = queryset.filter(domain__in=domains)
    updated = queryset.order_by("-last_seen_at").values_list("last_seen_at", flat=True).first()
    count = int(queryset.count())
    return f"{count}:{updated.isoformat() if updated else 'none'}"


def fetch_alias_rows(*, agency_id: int, domains: tuple[str, ...]) -> list[dict[str, Any]]:
    queryset = ImportAgencyAlias.objects.filter(agency_id=agency_id)
    if domains:
        queryset = queryset.filter(domain__in=domains)
    return list(
        queryset.values(
            "agency_id",
            "domain",
            "source_value_original",
            "source_value_normalized",
            "canonical_key",
            "canonical_label",
            "state",
            "confirm_count",
            "reject_count",
            "distinct_job_count",
            "metadata",
        )
    )


def import_learning_health_counts() -> dict[str, int]:
    manual_mapping_required_jobs = int(
        ImportJob.objects.filter(inference_summary__manual_mapping_required=True).count()
    )
    return {
        "trusted_agency_aliases": int(
            ImportAgencyAlias.objects.filter(state=ImportAgencyAlias.State.TRUSTED).count()
        ),
        "shadow_agency_aliases": int(
            ImportAgencyAlias.objects.filter(state=ImportAgencyAlias.State.SHADOW).count()
        ),
        "rejected_agency_aliases": int(
            ImportAgencyAlias.objects.filter(state=ImportAgencyAlias.State.REJECTED).count()
        ),
        "correction_signals": int(ImportCorrectionSignal.objects.count()),
        "agency_profiles": int(ImportAgencyProfile.objects.count()),
        "dead_letter_rows": int(ImportDeadLetterRow.objects.count()),
        "manual_mapping_required_jobs": manual_mapping_required_jobs,
    }


def bulk_create_correction_signals(signals: Iterable[ImportCorrectionSignal]) -> None:
    signal_list = list(signals)
    if not signal_list:
        return
    ImportCorrectionSignal.objects.bulk_create(signal_list)


def get_or_create_agency_alias(
    *,
    agency_id: int,
    domain: str,
    source_value_normalized: str,
    defaults: dict[str, Any],
) -> tuple[ImportAgencyAlias, bool]:
    return cast(
        tuple[ImportAgencyAlias, bool],
        ImportAgencyAlias.objects.get_or_create(
            agency_id=agency_id,
            domain=domain,
            source_value_normalized=source_value_normalized,
            defaults=defaults,
        ),
    )


def save_agency_alias(alias: ImportAgencyAlias, *, update_fields: list[str]) -> None:
    alias.save(update_fields=update_fields)


def fetch_agency_profile(*, agency_id: int) -> dict[str, Any] | None:
    row = (
        ImportAgencyProfile.objects.filter(agency_id=agency_id)
        .values(
            "agency_id",
            "memory_version",
            "preferred_language",
            "default_wilaya_code",
            "common_bundle_shape",
            "property_vocab",
            "location_abbreviations",
            "action_vocab",
            "header_vocab",
            "common_missing_fields",
            "last_imported_at",
        )
        .first()
    )
    return dict(row) if row else None


def upsert_agency_profile(*, agency_id: int, defaults: dict[str, Any]) -> ImportAgencyProfile:
    profile, _created = ImportAgencyProfile.objects.update_or_create(
        agency_id=agency_id,
        defaults=defaults,
    )
    return cast(ImportAgencyProfile, profile)


def bulk_create_dead_letter_rows(rows: Iterable[ImportDeadLetterRow]) -> None:
    row_list = list(rows)
    if not row_list:
        return
    ImportDeadLetterRow.objects.bulk_create(row_list)
