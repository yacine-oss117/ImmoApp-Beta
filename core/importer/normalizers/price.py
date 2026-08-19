"""Price normalizer for Algerian DZD and colloquial centime dialects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.importer.normalizers.base import NormalizeResult, RowContext
from core.importer.normalizers.text_utils import (
    canonicalize_text,
    convert_arabic_digits,
    strip_accents,
)

_EXPLICIT_DZD_PATTERN = re.compile(r"\b(?:dzd|da|dinar|dinars)\b|دينار|دج", re.IGNORECASE)
_EXPLICIT_CENTIME_PATTERN = re.compile(r"\b(?:centime|centimes|cts\.?|cts)\b", re.IGNORECASE)
_MONTHLY_PATTERN = re.compile(r"/\s*(?:mois|month|mensuel(?:le)?)\b", re.IGNORECASE)
_K_SUFFIX_PATTERN = re.compile(r"^(\d+(?:[.,]\d+)?)\s*[kK]$")
_MILLIARD_PATTERN = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(?:mrd|mrds|milliard|milliards)$", re.IGNORECASE
)
_MILLIARD_COMPOUND_PATTERN = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(?:mrd|mrds|milliard|milliards)\s+(\d+(?:[.,]\d+)?)$",
    re.IGNORECASE,
)
_MILLION_WORD_PATTERN = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:million|millions)$", re.IGNORECASE)
_M_SYMBOL_PATTERN = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([mM])$")
_GROUPED_SPACE_PATTERN = re.compile(r"^\d{1,3}(?:\s\d{3})+$")
_GROUPED_DOT_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_GROUPED_COMMA_PATTERN = re.compile(r"^\d{1,3}(?:,\d{3})+$")
_INTEGER_PATTERN = re.compile(r"^\d+$")
_DECIMAL_PATTERN = re.compile(r"^\d+[.,]\d+$")
_SUPPORTED_WORD_PATTERN = re.compile(
    r"^(?:\d+(?:[.,]\d+)?|\s|[kKmM]|mrd|mrds|milliard|milliards|million|millions)+$",
    re.IGNORECASE,
)
_SIGNED_CORE_PATTERN = re.compile(r"^([+-])\s*(.+)$")


@dataclass(frozen=True)
class _PriceCandidate:
    normalized_dzd: float | None
    dialect: str
    expression_kind: str
    confidence: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    extracted_extras: dict[str, object] = field(default_factory=dict)

    def as_dict(self, *, selected_by_context: bool = False) -> dict[str, object]:
        return {
            "normalized_dzd": self.normalized_dzd,
            "dialect": self.dialect,
            "expression_kind": self.expression_kind,
            "confidence": float(self.confidence),
            "reason_codes": list(self.reason_codes),
            "selected_by_context": bool(selected_by_context),
            "extracted_extras": dict(self.extracted_extras),
        }


def _clean_text(value: str) -> str:
    text = convert_arabic_digits(str(value or ""))
    return canonicalize_text(text)


def _normalize_price_alias_source(value: str) -> str:
    return strip_accents(_clean_text(value).lower()).replace(" ", "").replace(",", ".")


def _as_float(number_text: str) -> float:
    return float(str(number_text).replace(",", "."))


def _finalize_number(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _object_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def _object_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _candidate(
    *,
    normalized_dzd: float | None,
    dialect: str,
    expression_kind: str,
    confidence: float,
    reason_codes: list[str],
    extracted_extras: dict[str, object] | None = None,
) -> _PriceCandidate:
    return _PriceCandidate(
        normalized_dzd=_finalize_number(normalized_dzd),
        dialect=dialect,
        expression_kind=expression_kind,
        confidence=confidence,
        reason_codes=tuple(reason_codes),
        extracted_extras=dict(extracted_extras or {}),
    )


def _grouped_integer(text: str) -> int | None:
    if _GROUPED_SPACE_PATTERN.match(text):
        return int(text.replace(" ", ""))
    if _GROUPED_DOT_PATTERN.match(text):
        return int(text.replace(".", ""))
    if _GROUPED_COMMA_PATTERN.match(text):
        return int(text.replace(",", ""))
    if _INTEGER_PATTERN.match(text):
        return int(text)
    return None


def _parse_core_candidates(
    *,
    core: str,
    explicit_dzd: bool,
    explicit_centimes: bool,
    monthly: bool,
) -> list[_PriceCandidate]:
    if not core:
        return []

    extras: dict[str, object] = {"cadence": "monthly"} if monthly else {}

    match = _K_SUFFIX_PATTERN.match(core)
    if match:
        amount = _as_float(match.group(1)) * 1_000
        return [
            _candidate(
                normalized_dzd=amount,
                dialect="dzd_thousands",
                expression_kind="dzd_thousands",
                confidence=0.98,
                reason_codes=["k_suffix"],
                extracted_extras=extras,
            )
        ]

    match = _MILLIARD_COMPOUND_PATTERN.match(core)
    if match:
        major = _as_float(match.group(1))
        trailing = _as_float(match.group(2))
        if explicit_dzd:
            amount = (major * 1_000_000_000) + (trailing * 1_000_000)
            return [
                _candidate(
                    normalized_dzd=amount,
                    dialect="dzd_millions",
                    expression_kind="dzd_millions",
                    confidence=0.99,
                    reason_codes=["explicit_dzd_token", "milliard_compound_dzd"],
                    extracted_extras=extras,
                )
            ]
        amount = (major * 10_000_000) + (trailing * 10_000)
        return [
            _candidate(
                normalized_dzd=amount,
                dialect="centime_milliards",
                expression_kind="centime_milliards",
                confidence=0.97,
                reason_codes=["colloquial_milliard_compound"],
                extracted_extras=extras,
            )
        ]

    match = _MILLIARD_PATTERN.match(core)
    if match:
        amount = _as_float(match.group(1))
        if explicit_dzd:
            return [
                _candidate(
                    normalized_dzd=amount * 1_000_000_000,
                    dialect="dzd_millions",
                    expression_kind="dzd_millions",
                    confidence=0.99,
                    reason_codes=["explicit_dzd_token", "milliard_dzd"],
                    extracted_extras=extras,
                )
            ]
        return [
            _candidate(
                normalized_dzd=amount * 10_000_000,
                dialect="centime_milliards",
                expression_kind="centime_milliards",
                confidence=0.96,
                reason_codes=["colloquial_milliard_default"],
                extracted_extras=extras,
            )
        ]

    match = _MILLION_WORD_PATTERN.match(core) or _M_SYMBOL_PATTERN.match(core)
    if match:
        amount = _as_float(match.group(1))
        if explicit_dzd:
            return [
                _candidate(
                    normalized_dzd=amount * 1_000_000,
                    dialect="dzd_millions",
                    expression_kind=("monthly_variant" if monthly else "dzd_millions"),
                    confidence=0.99,
                    reason_codes=["explicit_dzd_token", "million_token"],
                    extracted_extras=extras,
                )
            ]
        if explicit_centimes:
            return [
                _candidate(
                    normalized_dzd=amount * 10_000,
                    dialect="centime_millions",
                    expression_kind=("monthly_variant" if monthly else "centime_millions"),
                    confidence=0.99,
                    reason_codes=["explicit_centime_token", "million_token"],
                    extracted_extras=extras,
                )
            ]
        if monthly:
            return [
                _candidate(
                    normalized_dzd=amount * 10_000,
                    dialect="centime_millions",
                    expression_kind="monthly_variant",
                    confidence=0.92,
                    reason_codes=["monthly_centime_default", "million_token"],
                    extracted_extras=extras,
                )
            ]
        return [
            _candidate(
                normalized_dzd=amount * 1_000_000,
                dialect="dzd_millions",
                expression_kind=("monthly_variant" if monthly else "dzd_millions"),
                confidence=0.74,
                reason_codes=["ambiguous_million_token"],
                extracted_extras=extras,
            ),
            _candidate(
                normalized_dzd=amount * 10_000,
                dialect="centime_millions",
                expression_kind=("monthly_variant" if monthly else "centime_millions"),
                confidence=0.74,
                reason_codes=["ambiguous_million_token"],
                extracted_extras=extras,
            ),
        ]

    grouped_integer = _grouped_integer(core)
    if grouped_integer is not None:
        if explicit_centimes:
            return [
                _candidate(
                    normalized_dzd=grouped_integer / 100,
                    dialect="centime_scalar",
                    expression_kind="centime_scalar",
                    confidence=0.98,
                    reason_codes=["explicit_centime_token", "raw_scalar"],
                    extracted_extras=extras,
                )
            ]
        return [
            _candidate(
                normalized_dzd=float(grouped_integer),
                dialect="raw_dzd",
                expression_kind="raw_dzd",
                confidence=1.0,
                reason_codes=["raw_scalar"],
                extracted_extras=extras,
            )
        ]

    if _DECIMAL_PATTERN.match(core):
        decimal_value = _as_float(core)
        if explicit_centimes:
            return [
                _candidate(
                    normalized_dzd=decimal_value / 100,
                    dialect="centime_scalar",
                    expression_kind="centime_scalar",
                    confidence=0.98,
                    reason_codes=["explicit_centime_token", "raw_decimal_scalar"],
                    extracted_extras=extras,
                )
            ]
        if explicit_dzd or decimal_value >= 1000:
            return [
                _candidate(
                    normalized_dzd=decimal_value,
                    dialect="raw_dzd",
                    expression_kind="raw_dzd",
                    confidence=0.92 if explicit_dzd else 0.88,
                    reason_codes=(
                        ["explicit_dzd_token", "raw_decimal_scalar"]
                        if explicit_dzd
                        else ["raw_decimal_scalar"]
                    ),
                    extracted_extras=extras,
                )
            ]
        return [
            _candidate(
                normalized_dzd=None,
                dialect="ambiguous",
                expression_kind="ambiguous_decimal",
                confidence=0.0,
                reason_codes=["ambiguous_decimal_no_scale"],
                extracted_extras=extras,
            )
        ]

    if _SUPPORTED_WORD_PATTERN.match(core):
        return []
    return []


def _extract_signed_core(core: str) -> tuple[str, bool]:
    match = _SIGNED_CORE_PATTERN.match(core)
    if not match:
        return core, False
    sign, unsigned_core = match.groups()
    return unsigned_core.strip(), sign == "-"


class PriceNormalizer:
    """Normalize price inputs into canonical DZD values."""

    def __init__(self, output_in_centimes: bool = False) -> None:
        self.output_in_centimes = output_in_centimes

    def candidate_records(
        self,
        value: str,
        context: RowContext | None = None,
    ) -> list[dict[str, object]]:
        if not value or not value.strip():
            return []
        cleaned = canonicalize_text(_clean_text(value))
        normalized_lower = strip_accents(cleaned.lower())
        monthly = bool(_MONTHLY_PATTERN.search(normalized_lower))
        explicit_dzd = bool(_EXPLICIT_DZD_PATTERN.search(normalized_lower))
        explicit_centimes = bool(_EXPLICIT_CENTIME_PATTERN.search(normalized_lower))

        core = _MONTHLY_PATTERN.sub("", normalized_lower).strip()
        core = _EXPLICIT_DZD_PATTERN.sub("", core).strip()
        core = _EXPLICIT_CENTIME_PATTERN.sub("", core).strip()
        core = " ".join(core.split())
        core, negative_price_detected = _extract_signed_core(core)

        candidates = _parse_core_candidates(
            core=core,
            explicit_dzd=explicit_dzd,
            explicit_centimes=explicit_centimes,
            monthly=monthly,
        )
        records = [candidate.as_dict() for candidate in candidates]
        if negative_price_detected:
            for record in records:
                extracted_extras = _object_dict(record.get("extracted_extras", {}))
                extracted_extras["negative_price_detected"] = True
                record["extracted_extras"] = extracted_extras
        return records

    def normalize(self, value: str, context: RowContext | None = None) -> NormalizeResult:
        if not value or not value.strip():
            return NormalizeResult(
                value=None,
                confidence=1.0,
                original=value,
                needs_review=False,
            )

        candidates = [
            self._candidate_from_dict(item) for item in self.candidate_records(value, context)
        ]
        if not candidates:
            return NormalizeResult(
                value=None,
                confidence=0.0,
                original=value,
                needs_review=True,
                to_remarks=f"Could not parse price: {value}",
            )

        negative_price_detected = any(
            bool(candidate.extracted_extras.get("negative_price_detected", False))
            for candidate in candidates
        )
        selected = self._select_candidate(value, candidates, context)
        if selected is None:
            ambiguity_reasons: list[str] = []
            if len(candidates) == 1 and candidates[0].normalized_dzd is None:
                ambiguity_reasons = list(candidates[0].reason_codes)
            else:
                ambiguity_reasons = sorted(
                    {code for candidate in candidates for code in candidate.reason_codes}
                ) or ["ambiguous_price_scale"]
            extracted_extras = {
                "interpretation_candidates": [
                    candidate.as_dict(selected_by_context=False) for candidate in candidates
                ],
                "price_ambiguity_reason_codes": ambiguity_reasons,
            }
            if negative_price_detected:
                extracted_extras["negative_price_detected"] = True
            return NormalizeResult(
                value=None,
                confidence=0.0,
                original=value,
                needs_review=True,
                extracted_extras=extracted_extras,
                to_remarks=("We found more than one possible price scale for this value."),
            )

        selected_candidate, selection_reason = selected
        serialized_candidates = [
            candidate.as_dict(selected_by_context=(candidate == selected_candidate))
            for candidate in candidates
        ]
        extracted_extras = dict(selected_candidate.extracted_extras)
        extracted_extras["interpretation_candidates"] = serialized_candidates
        extracted_extras["selected_price_dialect"] = selected_candidate.dialect
        extracted_extras["selected_expression_kind"] = selected_candidate.expression_kind
        extracted_extras["price_selection_reason"] = selection_reason
        if negative_price_detected:
            extracted_extras["negative_price_detected"] = True
            return NormalizeResult(
                value=None,
                confidence=0.0,
                original=value,
                needs_review=True,
                extracted_extras=extracted_extras,
                to_remarks="Negative price requires review.",
            )

        final_value = selected_candidate.normalized_dzd
        if self.output_in_centimes and final_value is not None:
            final_value = float(final_value) * 100
            final_value = _finalize_number(final_value)

        return NormalizeResult(
            value=final_value,
            confidence=float(selected_candidate.confidence),
            original=value,
            needs_review=False,
            extracted_extras=extracted_extras,
        )

    def _candidate_from_dict(self, payload: dict[str, object]) -> _PriceCandidate:
        normalized_dzd_raw = payload.get("normalized_dzd")
        confidence_raw = payload.get("confidence", 0.0)
        return _candidate(
            normalized_dzd=(
                float(normalized_dzd_raw) if isinstance(normalized_dzd_raw, (int, float)) else None
            ),
            dialect=str(payload.get("dialect", "unknown") or "unknown"),
            expression_kind=str(payload.get("expression_kind", "unknown") or "unknown"),
            confidence=(float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0),
            reason_codes=[str(code) for code in _object_list(payload.get("reason_codes", []))],
            extracted_extras=_object_dict(payload.get("extracted_extras", {})),
        )

    def _select_candidate(
        self,
        raw_value: str,
        candidates: list[_PriceCandidate],
        context: RowContext | None,
    ) -> tuple[_PriceCandidate, str] | None:
        anchored = [candidate for candidate in candidates if candidate.normalized_dzd is not None]
        if len(anchored) == 1:
            return anchored[0], "single_candidate"

        metadata = dict((context.metadata if context else {}) or {})
        header_unit_hint = str(metadata.get("price_unit_hint", "") or "").strip().lower()
        alias_map = _object_dict(metadata.get("price_aliases", {}))
        raw_key = _normalize_price_alias_source(raw_value)
        alias_entry = alias_map.get(raw_key)
        if isinstance(alias_entry, dict):
            alias_dialect = str(alias_entry.get("dialect", "") or "").strip()
            for candidate in anchored:
                if candidate.dialect == alias_dialect:
                    boosted = _candidate(
                        normalized_dzd=candidate.normalized_dzd,
                        dialect=candidate.dialect,
                        expression_kind=candidate.expression_kind,
                        confidence=max(candidate.confidence, 0.95),
                        reason_codes=list(candidate.reason_codes) + ["agency_price_alias"],
                        extracted_extras=candidate.extracted_extras,
                    )
                    return boosted, "agency_price_alias"

        if header_unit_hint in {"dzd", "centime"}:
            preferred_dialects = (
                {"raw_dzd", "dzd_thousands", "dzd_millions"}
                if header_unit_hint == "dzd"
                else {"centime_scalar", "centime_millions", "centime_milliards"}
            )
            for candidate in anchored:
                if candidate.dialect in preferred_dialects:
                    boosted = _candidate(
                        normalized_dzd=candidate.normalized_dzd,
                        dialect=candidate.dialect,
                        expression_kind=candidate.expression_kind,
                        confidence=max(candidate.confidence, 0.96),
                        reason_codes=list(candidate.reason_codes)
                        + [f"header_explicit_{header_unit_hint}"],
                        extracted_extras=candidate.extracted_extras,
                    )
                    return boosted, f"header_explicit_{header_unit_hint}"

        hint_dialect = str(metadata.get("price_dialect_hint", "") or "").strip()
        hint_confidence_raw = metadata.get("price_dialect_confidence", 0.0)
        hint_confidence = (
            float(hint_confidence_raw) if isinstance(hint_confidence_raw, (int, float)) else 0.0
        )
        if hint_dialect and hint_confidence >= 0.8:
            for candidate in anchored:
                if candidate.dialect == hint_dialect:
                    boosted = _candidate(
                        normalized_dzd=candidate.normalized_dzd,
                        dialect=candidate.dialect,
                        expression_kind=candidate.expression_kind,
                        confidence=max(candidate.confidence, min(0.94, hint_confidence + 0.04)),
                        reason_codes=list(candidate.reason_codes) + ["column_price_dialect_hint"],
                        extracted_extras=candidate.extracted_extras,
                    )
                    return boosted, "column_price_dialect_hint"
        return None

    def format_display(self, price: int | float | None) -> str:
        if price is None:
            return ""
        numeric = int(price) if float(price).is_integer() else float(price)
        formatted = f"{numeric:,}".replace(",", " ")
        return f"{formatted} DA"

    def format_short(self, price: int | float | None) -> str:
        if price is None:
            return ""
        numeric = float(price)
        if numeric >= 1_000_000:
            millions = numeric / 1_000_000
            if millions.is_integer():
                return f"{int(millions)}M"
            return f"{millions:.1f}M"
        if numeric >= 1_000:
            thousands = numeric / 1_000
            if thousands.is_integer():
                return f"{int(thousands)}K"
            return f"{thousands:.1f}K"
        return str(int(numeric) if numeric.is_integer() else numeric)
