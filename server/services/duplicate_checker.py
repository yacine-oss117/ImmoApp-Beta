"""
Cross-database duplicate checker for imports.

Checks if imported phone numbers or emails already exist
in the database, preventing accidental duplicates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

import psycopg

from core.ale_utils import MASK_BIDX_PREFIX
from core.blind_index import blind_index_for_agency, blind_index_for_write
from core.importer.security import import_security_limits
from core.utils.common import phone_digits
from server.services.import_review_policy import REVIEW_AMBIGUOUS, UPDATE_EXISTING

logger = logging.getLogger(__name__)
_RETRYABLE_DUPLICATE_CHECK_ERRORS = (
    psycopg.InterfaceError,
    psycopg.OperationalError,
    ConnectionError,
    TimeoutError,
)


class DuplicateCheckUnavailableError(RuntimeError):
    """Duplicate-check infrastructure failed and the import must fail closed."""


@dataclass
class DbDuplicateMatch:
    """A row that matches an existing database record.

    Attributes:
        row_index: Row number in the import (1-based).
        field_name: Field that matched (e.g. "phone").
        field_value: Normalized value that matched.
        existing_id: ID of the existing record in the database.
    """

    row_index: int
    field_name: str
    field_value: str
    candidates: list[DbDuplicateCandidate] = field(default_factory=list)
    suggested_action: str = REVIEW_AMBIGUOUS
    suggested_existing_id: int = 0
    total_candidate_count: int = 0

    @property
    def existing_id(self) -> int:
        if self.suggested_existing_id > 0:
            return int(self.suggested_existing_id)
        if not self.candidates:
            return 0
        return int(self.candidates[0].existing_id)


@dataclass
class DbDuplicateCandidate:
    """Existing DB record that matches an imported row."""

    existing_id: int
    row_version: int
    family_name: str
    phone: str
    status: str
    remarks: str = ""
    match_confidence: float = 0.0
    match_reasons: list[str] = field(default_factory=list)


@dataclass
class DbDuplicateResult:
    """Result of checking rows against the database.

    Attributes:
        matches: Rows that match existing DB records.
        clean_indices: Set of row indices with no DB duplicates.
    """

    matches: list[DbDuplicateMatch] = field(default_factory=list)
    clean_indices: set[int] = field(default_factory=set)

    @property
    def has_duplicates(self) -> bool:
        return len(self.matches) > 0


def _normalize_phone_for_dedup(phone: str) -> str:
    """Normalize phone for duplicate detection.

    Strips all formatting and converts Algerian prefixes
    to a consistent 10-digit format.
    """
    if not phone:
        return ""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if digits.startswith("00213"):
        digits = "0" + digits[5:]
    elif digits.startswith("213") and len(digits) > 9:
        digits = "0" + digits[3:]
    if len(digits) == 9 and digits[0] in "567":
        digits = "0" + digits
    return digits


def _phone_lookup_variants(phone: str) -> list[str]:
    raw_digits = phone_digits(phone)
    normalized_phone = _normalize_phone_for_dedup(phone)
    variants: set[str] = set()
    for candidate in (raw_digits, normalized_phone):
        if candidate and len(candidate) >= 9:
            variants.add(candidate)
    if normalized_phone and len(normalized_phone) == 10 and normalized_phone.startswith("0"):
        tail = normalized_phone[1:]
        variants.update({tail, f"213{tail}", f"00213{tail}"})
    elif raw_digits.startswith("00213") and len(raw_digits) > 12:
        tail = raw_digits[5:]
        variants.update({tail, f"0{tail}", f"213{tail}"})
    elif raw_digits.startswith("213") and len(raw_digits) > 11:
        tail = raw_digits[3:]
        variants.update({tail, f"0{tail}", f"00213{tail}"})
    return sorted({variant for variant in variants if len(variant) >= 9})


def _masked_phone_probes(phone: str, *, agency_id: int | None) -> list[str]:
    probes: set[str] = set()
    for variant in _phone_lookup_variants(phone):
        try:
            blind_value = MASK_BIDX_PREFIX + (
                blind_index_for_agency(variant, agency_id=int(agency_id))
                if agency_id is not None
                else blind_index_for_write(variant)
            )
        except RuntimeError:
            continue
        probes.add(blind_value)
    return sorted(probes)


def _plaintext_phone_probes(phone: str) -> list[str]:
    return _phone_lookup_variants(phone)


def _int_from_row_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _normalize_name_for_match(value: str | object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    compact = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(compact.split())


def _name_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return max(0.0, min(1.0, SequenceMatcher(None, left, right).ratio()))


def _score_candidate(
    *,
    source_phone: str,
    source_name: str,
    candidate: DbDuplicateCandidate,
) -> DbDuplicateCandidate:
    score = 0.0
    reasons: list[str] = []
    candidate_phone = _normalize_phone_for_dedup(candidate.phone)
    candidate_name = _normalize_name_for_match(candidate.family_name)
    if source_phone and source_phone == candidate_phone:
        score += 0.75
        reasons.append("same phone")
    similarity = _name_similarity(source_name, candidate_name)
    if source_name and candidate_name and source_name == candidate_name:
        score += 0.22
        reasons.append("same name")
    elif similarity >= 0.94:
        score += 0.16
        reasons.append("very similar name")
    elif similarity >= 0.84:
        score += 0.08
        reasons.append("similar name")
    if str(candidate.status or "").strip().lower() in {"active", "available"}:
        score += 0.02
        reasons.append("active record")
    candidate.match_confidence = round(min(1.0, score), 3)
    candidate.match_reasons = reasons
    return candidate


def _score_candidates_for_row(
    source_data: dict[str, Any],
    candidates: list[DbDuplicateCandidate],
) -> tuple[list[DbDuplicateCandidate], str, int]:
    source_phone = _normalize_phone_for_dedup(str(source_data.get("phone", "") or ""))
    source_name = _normalize_name_for_match(
        source_data.get("family_name", "") or source_data.get("name", "")
    )
    scored = [
        _score_candidate(
            source_phone=source_phone,
            source_name=source_name,
            candidate=DbDuplicateCandidate(
                existing_id=int(candidate.existing_id),
                row_version=int(candidate.row_version),
                family_name=str(candidate.family_name),
                phone=str(candidate.phone),
                remarks=str(candidate.remarks),
                status=str(candidate.status),
            ),
        )
        for candidate in candidates
    ]
    scored.sort(key=lambda candidate: (-candidate.match_confidence, candidate.existing_id))
    if not scored:
        return scored, REVIEW_AMBIGUOUS, 0
    top = scored[0]
    runner_up = scored[1].match_confidence if len(scored) > 1 else 0.0
    max_candidates = import_security_limits().max_duplicate_candidates
    display_candidates = scored[:max_candidates]
    if top.match_confidence >= 0.9 and (
        len(scored) == 1 or top.match_confidence - runner_up >= 0.12
    ):
        return display_candidates, UPDATE_EXISTING, int(top.existing_id)
    return display_candidates, REVIEW_AMBIGUOUS, int(top.existing_id)


class DatabaseDuplicateChecker:
    """Check imported rows against existing database records.

    Performs batch lookups to avoid N+1 queries.
    """

    @staticmethod
    def _table_for_entity(entity_type: str) -> str:
        if entity_type == "client":
            return "clients"
        if entity_type == "listing":
            return "listings"
        raise ValueError(f"Unsupported entity_type for duplicate check: {entity_type!r}")

    def check_phones(
        self,
        rows: list[dict[str, Any]],
        entity_type: str,
        session: Any,
        agency_id: int | None = None,
    ) -> DbDuplicateResult:
        """Check phone numbers against the database.

        Args:
            rows: List of normalized row dicts with 1-based row numbers.
                  Each dict must have at least {"row": int, "data": dict}.
            entity_type: "client" or "listing".
            session: Database session (from UoW).

        Returns:
            DbDuplicateResult with matches and clean indices.
        """
        # Collect all phone values for batch lookup
        phones_by_row: dict[str, list[int]] = {}  # normalized_phone → [row_indices]

        for entry in rows:
            row_num = entry.get("row", 0)
            data = entry.get("data", {})
            phone = data.get("phone", "")
            if phone:
                normalized = _normalize_phone_for_dedup(str(phone))
                if len(normalized) >= 9:
                    if normalized not in phones_by_row:
                        phones_by_row[normalized] = []
                    phones_by_row[normalized].append(row_num)

        if not phones_by_row:
            return DbDuplicateResult(clean_indices={e.get("row", 0) for e in rows})

        # Batch lookup
        existing = self._lookup_phones(
            list(phones_by_row.keys()),
            entity_type,
            session,
            agency_id=agency_id,
        )

        matches: list[DbDuplicateMatch] = []
        dup_row_indices: set[int] = set()
        row_sources = {
            int(entry.get("row", 0) or 0): dict(entry.get("data", {}) or {}) for entry in rows
        }

        for phone, candidates in existing.items():
            for row_num in phones_by_row.get(phone, []):
                scored_candidates, suggested_action, suggested_existing_id = (
                    _score_candidates_for_row(
                        row_sources.get(row_num, {}),
                        list(candidates),
                    )
                )
                matches.append(
                    DbDuplicateMatch(
                        row_index=row_num,
                        field_name="phone",
                        field_value=phone,
                        candidates=scored_candidates,
                        suggested_action=suggested_action,
                        suggested_existing_id=suggested_existing_id,
                        total_candidate_count=len(candidates),
                    )
                )
                dup_row_indices.add(row_num)

        all_row_indices = {e.get("row", 0) for e in rows}
        clean_indices = all_row_indices - dup_row_indices

        return DbDuplicateResult(
            matches=matches,
            clean_indices=clean_indices,
        )

    def _lookup_phones(
        self,
        phones: list[str],
        entity_type: str,
        session: Any,
        *,
        agency_id: int | None = None,
    ) -> dict[str, list[DbDuplicateCandidate]]:
        """Batch lookup phones in the database.

        Args:
            phones: Normalized phone numbers to look up.
            entity_type: Entity type to search in.
            session: Database session.

        Returns:
            Dict of {phone: [matching candidates]}.
        """
        if not phones:
            return {}

        table = self._table_for_entity(entity_type)
        try:
            normalized_phones = [
                normalized
                for phone in phones
                if (normalized := _normalize_phone_for_dedup(phone)) and len(normalized) >= 9
            ]
            if not normalized_phones:
                return {}
            masked_lookup_map: dict[str, str] = {}
            plaintext_lookup_map: dict[str, str] = {}
            for normalized_phone in normalized_phones:
                for probe in _masked_phone_probes(normalized_phone, agency_id=agency_id):
                    masked_lookup_map[probe] = normalized_phone
                for probe in _plaintext_phone_probes(normalized_phone):
                    plaintext_lookup_map[probe] = normalized_phone

            def _fetch_rows(probes: list[str]) -> list[dict[str, object]]:
                if not probes:
                    return []
                params: list[object] = [probes]
                query = f"""
                    SELECT t.id, t.row_version, t.family_name, t.phone, t.remarks, t.status
                    FROM {table} t
                    WHERE t.phone = ANY(%s)
                      AND t.deleted_at IS NULL
                """
                if agency_id is not None:
                    query += " AND t.agency_id = %s"
                    params.append(int(agency_id))
                query += " ORDER BY t.id"
                return list(session.execute(query, params).fetchall())

            rows = [
                *_fetch_rows(sorted(masked_lookup_map.keys())),
                *_fetch_rows(sorted(plaintext_lookup_map.keys())),
            ]
            result: dict[str, list[DbDuplicateCandidate]] = {}
            seen_candidates: set[tuple[str, int]] = set()
            for row in rows:
                stored_phone = str(row.get("phone", "") or "")
                phone_val = (
                    masked_lookup_map.get(stored_phone)
                    or plaintext_lookup_map.get(stored_phone)
                    or _normalize_phone_for_dedup(stored_phone)
                )
                if phone_val:
                    row_id = _int_from_row_value(row.get("id", 0))
                    candidate_key = (phone_val, row_id)
                    if row_id > 0 and candidate_key in seen_candidates:
                        continue
                    if row_id > 0:
                        seen_candidates.add(candidate_key)
                    result.setdefault(phone_val, []).append(
                        DbDuplicateCandidate(
                            existing_id=row_id,
                            row_version=_int_from_row_value(row.get("row_version", 0)),
                            family_name=str(row.get("family_name", "") or ""),
                            phone=phone_val,
                            remarks=str(row.get("remarks", "") or ""),
                            status=str(row.get("status", "") or ""),
                        )
                    )
            return result
        except _RETRYABLE_DUPLICATE_CHECK_ERRORS as exc:
            logger.exception("Failed to check phone duplicates in DB")
            raise DuplicateCheckUnavailableError(
                "Duplicate verification is temporarily unavailable."
            ) from exc

    def filter_batch(
        self,
        batch: list[dict[str, Any]],
        entity_type: str,
        session: Any,
        *,
        agency_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Filter a batch of flat row dicts against the database.

        Args:
            batch: List of validated row dicts (flat, with 'phone' key).
            entity_type: "client" or "listing".
            session: Database session (from UoW).

        Returns:
            Tuple of (clean_rows, duplicate_rows).
        """
        if not batch:
            return batch, []

        phones: list[str] = []
        for row in batch:
            phone = row.get("phone", "")
            if phone:
                phones.append(_normalize_phone_for_dedup(str(phone)))

        phones = [p for p in phones if len(p) >= 9]
        if not phones:
            return batch, []

        entries = [
            {
                "row": index + 1,
                "data": row,
            }
            for index, row in enumerate(batch)
        ]
        result = self.check_phones(
            entries,
            entity_type,
            session,
            agency_id=agency_id,
        )
        if not result.has_duplicates:
            return batch, []

        duplicates_by_index = {match.row_index for match in result.matches}
        clean: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        for index, row in enumerate(batch, start=1):
            if index in duplicates_by_index:
                duplicates.append(row)
            else:
                clean.append(row)

        return clean, duplicates


__all__ = [
    "DatabaseDuplicateChecker",
    "DbDuplicateCandidate",
    "DbDuplicateMatch",
    "DbDuplicateResult",
    "DuplicateCheckUnavailableError",
    "_normalize_phone_for_dedup",
]
