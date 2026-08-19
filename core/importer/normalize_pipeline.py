"""
Normalization pipeline for import data.

Routes each field to the appropriate normalizer based on its detected type,
producing confidence-scored results with review flags for uncertain values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.importer.normalizers.action import ActionNormalizer
from core.importer.normalizers.base import NormalizeResult, RowContext
from core.importer.normalizers.boolean import BooleanNormalizer
from core.importer.normalizers.location_normalizer import LocationNormalizer
from core.importer.normalizers.phone import PhoneNormalizer
from core.importer.normalizers.price import PriceNormalizer
from core.importer.normalizers.property_type import PropertyTypeNormalizer
from core.importer.type_parser import TypeParser
from core.importer.validation import ImportValidationError, ImportValidator


@dataclass
class ReviewField:
    """A single field that needs human review.

    Attributes:
        field_name: Database field name.
        original_value: Raw value from the file.
        normalized_value: Best-effort normalized value (may be None).
        confidence: Normalizer confidence 0.0-1.0.
        remark: Human-readable reason for review.
    """

    field_name: str
    original_value: str
    normalized_value: object
    confidence: float
    remark: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtraConflict:
    """A conflicting extracted extra emitted by multiple normalizers in one row."""

    key: str
    first_field: str
    first_value: object
    second_field: str
    second_value: object
    reason_code: str = "extracted_extra_conflict"


@dataclass
class NormalizedRow:
    """Result of normalizing a single row.

    Attributes:
        data: Normalized field values.
        confidence: Minimum confidence across all fields.
        needs_review: True if any field has low confidence.
        review_fields: Fields that need human review.
        remarks: Accumulated normalizer remarks.
        extras: Extra fields extracted by normalizers (e.g. beds from F3).
        extra_conflicts: Conflicting extracted extras that forced review.
    """

    data: dict[str, Any]
    confidence: float = 1.0
    needs_review: bool = False
    review_fields: list[ReviewField] = field(default_factory=list)
    remarks: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    extra_conflicts: list[ExtraConflict] = field(default_factory=list)
    field_results: dict[str, NormalizeResult] = field(default_factory=dict)
    recovered_fields: list[dict[str, Any]] = field(default_factory=list)
    recovery_candidates: list[dict[str, Any]] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    recoverability_class: str = "auto_recoverable"


# Detected column types that route to normalizers
_PHONE_TYPES = {"phone"}
_PRICE_TYPES = {"price"}
_LOCATION_TYPES = {"location"}
_WILAYA_TYPES = {"wilaya"}
_PROPERTY_TYPE_TYPES = {"type"}
_ACTION_TYPES = {"action"}
_BOOLEAN_TYPES = {
    "furnished",
    "elevator",
    "parking",
    "accessibility_required",
    "accessibility_supported",
    "price_negotiable",
}
_NUMERIC_TYPES = {
    "surface",
    "surface_min",
    "surface_max",
    "rooms",
    "beds",
    "beds_min",
    "floor",
    "floor_min",
    "floor_max",
    "budget_min",
    "budget_max",
    "budget",
}
_PASSTHROUGH_TYPES = {"name", "email", "date", "notes", "unknown"}
_SURFACE_FIELDS = {"surface", "surface_min", "surface_max"}
_INTEGER_QUANTITY_FIELDS = {"rooms", "floor", "floor_min", "floor_max", "beds", "beds_min"}
_MERGEABLE_EXTRACTED_EXTRA_KEYS = {
    "beds",
    "surface_min",
    "surface_max",
    "floor_min",
    "floor_max",
}
_SURFACE_PATTERN = re.compile(
    r"^\s*(-?\d+(?:[.,]\d+)?)\s*(?:m²|m2|sqm|m|metr|metre|metres|meter|meters)?\s*$",
    re.IGNORECASE,
)
_SURFACE_RANGE_PATTERN = re.compile(
    r"^\s*(-?\d+(?:[.,]\d+)?)\s*(?:-|/|a|à|to)\s*(-?\d+(?:[.,]\d+)?)\s*(?:m²|m2|sqm|m|metr|metre|metres|meter|meters)?\s*$",
    re.IGNORECASE,
)
_APPROXIMATE_PREFIX_PATTERN = re.compile(r"^\s*(?:environ|~|circa)\s+", re.IGNORECASE)
_INTEGER_QUANTITY_PATTERN = re.compile(
    r"^\s*(-?\d+)\s*(?:room|rooms|piece|pieces|pi[eè]ce|pi[eè]ces|bed|beds|chambre|chambres|floor|etage|étage)?\s*$",
    re.IGNORECASE,
)
_INTEGER_RANGE_PATTERN = re.compile(
    r"^\s*(-?\d+)\s*(?:-|/|a|à|to)\s*(-?\d+)\s*(?:room|rooms|piece|pieces|pi[eè]ce|pi[eè]ces|bed|beds|chambre|chambres|floor|etage|étage)?\s*$",
    re.IGNORECASE,
)
_FLOOR_TEXT_RANGE_PATTERN = re.compile(
    r"^\s*(?:entre\s+)?(-?\d+)\s*(?:et|a|à|to|-|/)\s*(-?\d+)\s*$", re.IGNORECASE
)
_GENERIC_NUMERIC_PATTERN = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*$")
_GROUND_FLOOR_PATTERN = re.compile(r"^\s*rdc(?:\s+sur[- ]?elev[eé])?\s*$", re.IGNORECASE)
_FLOOR_ORDINAL_PATTERN = re.compile(
    r"^\s*(-?\d+)(?:er|eme|e|st|nd|rd|th)?\s*(?:floor|etage|étage)?\s*$",
    re.IGNORECASE,
)
_WORD_NUMBERS = {
    "zero": 0,
    "zéro": 0,
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "اول": 1,
    "الأول": 1,
    "الاول": 1,
}

# Confidence threshold: below this, mark for review
REVIEW_THRESHOLD = 0.85


class NormalizationPipeline:
    """Applies all normalizers to a mapped row based on detected column types.

    Usage::

        pipeline = NormalizationPipeline(
            entity_type="client",
            column_types={"Telephone": "phone", "Budget": "price", ...},
        )
        result = pipeline.normalize_row({"Telephone": "05 55 12 34 56", ...})
    """

    def __init__(
        self,
        entity_type: str,
        column_types: dict[str, str] | None = None,
        field_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            entity_type: Target entity type ('client' or 'listing').
            column_types: Mapping of column_name → detected_type.
                          If None, all fields get passthrough normalization.
        """
        self.entity_type = entity_type
        self.column_types = column_types or {}
        self.field_metadata = {
            str(field): dict(metadata)
            for field, metadata in dict(field_metadata or {}).items()
            if str(field).strip()
        }

        # Lazy-init normalizers (some are expensive, e.g. LocationNormalizer)
        self._phone: PhoneNormalizer | None = None
        self._price: PriceNormalizer | None = None
        self._location: LocationNormalizer | None = None
        self._property_type: PropertyTypeNormalizer | None = None
        self._action: ActionNormalizer | None = None
        self._boolean: BooleanNormalizer | None = None

    # -- Normalizer accessors (lazy init) --

    @property
    def phone(self) -> PhoneNormalizer:
        if self._phone is None:
            self._phone = PhoneNormalizer()
        return self._phone

    @property
    def price(self) -> PriceNormalizer:
        if self._price is None:
            self._price = PriceNormalizer()
        return self._price

    @property
    def location(self) -> LocationNormalizer:
        if self._location is None:
            self._location = LocationNormalizer()
        return self._location

    @property
    def property_type(self) -> PropertyTypeNormalizer:
        if self._property_type is None:
            self._property_type = PropertyTypeNormalizer()
        return self._property_type

    @property
    def action(self) -> ActionNormalizer:
        if self._action is None:
            action_entity = self.entity_type
            if action_entity == "demande":
                action_entity = "client"
            elif action_entity == "offer":
                action_entity = "listing"
            self._action = ActionNormalizer(entity_type=action_entity)
        return self._action

    @property
    def boolean(self) -> BooleanNormalizer:
        if self._boolean is None:
            self._boolean = BooleanNormalizer()
        return self._boolean

    # -- Core method --

    def normalize_row(
        self,
        row: dict[str, Any],
        context: RowContext | None = None,
    ) -> NormalizedRow:
        """Normalize all fields in a row.

        Args:
            row: Mapped row (field_name → raw value).
            context: Optional cross-column context for hints.

        Returns:
            NormalizedRow with data, confidence, and review flags.
        """
        data: dict[str, Any] = {}
        min_confidence = 1.0
        needs_review = False
        review_fields: list[ReviewField] = []
        remarks: list[str] = []
        extras: dict[str, Any] = {}
        extra_conflicts: list[ExtraConflict] = []
        field_results: dict[str, NormalizeResult] = {}
        extra_sources: dict[str, tuple[str, object]] = {}
        conflicted_extra_keys: set[str] = set()

        # Build context from the row if not provided
        if context is None:
            context = self._build_context(row)

        for field_name, raw_value in row.items():
            col_type = self.column_types.get(field_name, "unknown")
            raw_str = str(raw_value).strip() if raw_value is not None else ""

            if not raw_str:
                data[field_name] = None
                continue

            field_context = self._context_for_field(context, field_name, col_type)
            result = self._normalize_field(field_name, raw_str, col_type, field_context)
            field_results[field_name] = result

            data[field_name] = result.value
            min_confidence = min(min_confidence, result.confidence)

            # Collect extras (e.g. beds extracted from property type "F3")
            if result.extracted_extras:
                for extra_key, extra_value in result.extracted_extras.items():
                    if extra_key not in _MERGEABLE_EXTRACTED_EXTRA_KEYS:
                        continue
                    if extra_key in conflicted_extra_keys:
                        continue
                    if extra_key not in extras:
                        extras[extra_key] = extra_value
                        extra_sources[extra_key] = (field_name, extra_value)
                        continue
                    if extras[extra_key] == extra_value:
                        continue
                    first_field, first_value = extra_sources.get(
                        extra_key,
                        ("", extras.get(extra_key)),
                    )
                    extras.pop(extra_key, None)
                    extra_sources.pop(extra_key, None)
                    conflicted_extra_keys.add(extra_key)
                    needs_review = True
                    conflict = ExtraConflict(
                        key=extra_key,
                        first_field=first_field,
                        first_value=first_value,
                        second_field=field_name,
                        second_value=extra_value,
                    )
                    extra_conflicts.append(conflict)
                    conflict_remark = (
                        f"Conflicting extracted value for {extra_key}: "
                        f"{first_field or 'unknown'}={first_value!r} vs {field_name}={extra_value!r}"
                    )
                    remarks.append(conflict_remark)
                    review_fields.append(
                        ReviewField(
                            field_name=field_name,
                            original_value=raw_str,
                            normalized_value=result.value,
                            confidence=min(result.confidence, 0.5),
                            remark=conflict_remark,
                            metadata={
                                "column_type": col_type,
                                "extra_conflict": {
                                    "key": conflict.key,
                                    "first_field": conflict.first_field,
                                    "first_value": conflict.first_value,
                                    "second_field": conflict.second_field,
                                    "second_value": conflict.second_value,
                                    "reason_code": conflict.reason_code,
                                },
                                "source_header": str(
                                    self.field_metadata.get(field_name, {}).get("source_header", "")
                                    or ""
                                ),
                            },
                        )
                    )

            if result.to_remarks:
                remarks.append(result.to_remarks)

            if result.needs_review or result.confidence < REVIEW_THRESHOLD:
                needs_review = True
                review_fields.append(
                    ReviewField(
                        field_name=field_name,
                        original_value=raw_str,
                        normalized_value=result.value,
                        confidence=result.confidence,
                        remark=result.to_remarks or f"Low confidence: {result.confidence:.0%}",
                        metadata=self._review_field_metadata(
                            field_name=field_name,
                            col_type=col_type,
                            result=result,
                        ),
                    )
                )

        # Merge extracted extras into data (e.g. beds from F3)
        for key, val in extras.items():
            if key not in data:
                data[key] = val
            elif data[key] != val:
                remarks.append(
                    f"Extracted {key}={val} from normalizer but explicit column has {key}={data[key]}"
                )

        return NormalizedRow(
            data=data,
            confidence=min_confidence,
            needs_review=needs_review,
            review_fields=review_fields,
            remarks=remarks,
            extras=extras,
            extra_conflicts=extra_conflicts,
            field_results=field_results,
        )

    # -- Field routing --

    def _normalize_field(
        self,
        field_name: str,
        raw_value: str,
        col_type: str,
        context: RowContext,
    ) -> NormalizeResult:
        """Route a field to the appropriate normalizer."""
        if col_type in _PHONE_TYPES:
            return self.phone.normalize(raw_value, context)

        if col_type in _PRICE_TYPES:
            return self.price.normalize(raw_value, context)

        if col_type in _LOCATION_TYPES:
            return self.location.normalize(raw_value, context)

        if col_type in _WILAYA_TYPES:
            return self._normalize_wilaya(raw_value, context)

        if col_type in _PROPERTY_TYPE_TYPES:
            return self.property_type.normalize(raw_value, context)

        if col_type in _ACTION_TYPES:
            return self.action.normalize(raw_value, context)

        if col_type in _BOOLEAN_TYPES:
            return self.boolean.normalize(raw_value, context)

        if col_type in _NUMERIC_TYPES:
            return self._normalize_numeric(raw_value, field_name)

        # Passthrough: sanitize string only
        return self._normalize_passthrough(raw_value, field_name)

    def _normalize_wilaya(
        self,
        raw_value: str,
        context: RowContext,
    ) -> NormalizeResult:
        """Normalize a wilaya value.

        Tries numeric code first, then falls back to location normalizer
        for fuzzy text matching.
        """
        # Try as numeric wilaya code (1-58)
        cleaned = raw_value.strip()
        try:
            code = int(cleaned)
            if 1 <= code <= 58:
                return NormalizeResult(
                    value=code,
                    confidence=1.0,
                    original=raw_value,
                    needs_review=False,
                )
        except ValueError:
            pass

        # Fall back to location normalizer for text matching
        result = self.location.normalize(raw_value, context)
        if result.extracted_extras and result.extracted_extras.get("is_wilaya"):
            # Location normalizer found a wilaya match
            try:
                wilaya_code = int(str(result.value))
                return NormalizeResult(
                    value=wilaya_code,
                    confidence=result.confidence,
                    original=raw_value,
                    needs_review=result.needs_review,
                    extracted_extras=result.extracted_extras,
                    to_remarks=result.to_remarks,
                )
            except (ValueError, TypeError):
                pass

        return result

    def _normalize_numeric(
        self,
        raw_value: str,
        field_name: str,
    ) -> NormalizeResult:
        """Normalize a numeric field (surface, rooms, floor)."""
        try:
            normalized = self._normalize_numeric_value(raw_value, field_name)
            if normalized is not None:
                return normalized
            num = self._parse_numeric_value(raw_value, field_name)
            # Surface and rooms should be positive
            if num < 0 and field_name not in {"floor", "floor_min", "floor_max"}:
                return NormalizeResult(
                    value=None,
                    confidence=0.3,
                    original=raw_value,
                    needs_review=True,
                    to_remarks=f"Negative {field_name}: {raw_value}",
                )

            if field_name in _INTEGER_QUANTITY_FIELDS:
                return NormalizeResult(
                    value=int(num),
                    confidence=1.0,
                    original=raw_value,
                )
            return NormalizeResult(
                value=num,
                confidence=1.0,
                original=raw_value,
            )
        except ValueError:
            return NormalizeResult(
                value=None,
                confidence=0.0,
                original=raw_value,
                needs_review=True,
                to_remarks=f"Cannot parse {field_name}: {raw_value}",
            )

    def _normalize_numeric_value(
        self,
        raw_value: str,
        field_name: str,
    ) -> NormalizeResult | None:
        text = str(raw_value or "").strip()
        if not text:
            return None
        if field_name in {"surface_min", "surface_max"}:
            return self._normalize_surface_range_value(text, field_name)
        if field_name in {"floor_min", "floor_max"}:
            return self._normalize_floor_range_value(text, field_name)
        if field_name == "beds_min":
            return self._normalize_beds_min_value(text)
        if field_name == "surface":
            return self._normalize_surface_scalar_value(text)
        if field_name == "floor":
            return self._normalize_floor_scalar_value(text)
        return None

    def _normalize_passthrough(
        self,
        raw_value: str,
        field_name: str,
    ) -> NormalizeResult:
        """Sanitize a string field without domain-specific normalization."""
        try:
            sanitized = ImportValidator.sanitize_string(raw_value, field_name)
            return NormalizeResult(
                value=sanitized,
                confidence=1.0,
                original=raw_value,
            )
        except ImportValidationError as exc:
            return NormalizeResult(
                value=None,
                confidence=0.0,
                original=raw_value,
                needs_review=True,
                to_remarks=f"Sanitization failed for {field_name}: {exc.message}",
            )

    def _parse_numeric_value(self, raw_value: str, field_name: str) -> float:
        if field_name in _SURFACE_FIELDS:
            return self._parse_surface_value(raw_value)
        if field_name in _INTEGER_QUANTITY_FIELDS:
            return float(self._parse_integer_quantity_value(raw_value))
        return self._parse_generic_numeric_value(raw_value)

    def _parse_surface_value(self, raw_value: str) -> float:
        match = _SURFACE_PATTERN.match(raw_value)
        if not match:
            raise ValueError(raw_value)
        return self._coerce_numeric_token(str(match.group(1)))

    def _parse_integer_quantity_value(self, raw_value: str) -> int:
        value = self._parse_word_number(raw_value)
        if value is not None:
            return value
        match = _INTEGER_QUANTITY_PATTERN.match(raw_value)
        if not match:
            raise ValueError(raw_value)
        return int(str(match.group(1)))

    def _parse_generic_numeric_value(self, raw_value: str) -> float:
        normalized = raw_value.replace(" ", "")
        match = _GENERIC_NUMERIC_PATTERN.match(normalized)
        if not match:
            raise ValueError(raw_value)
        return self._coerce_numeric_token(str(match.group(1)))

    def _parse_word_number(self, raw_value: str) -> int | None:
        normalized = str(raw_value or "").strip().lower()
        return _WORD_NUMBERS.get(normalized)

    def _normalize_surface_scalar_value(self, raw_value: str) -> NormalizeResult | None:
        approximate = bool(_APPROXIMATE_PREFIX_PATTERN.match(raw_value))
        normalized = _APPROXIMATE_PREFIX_PATTERN.sub("", raw_value).strip()
        match = _SURFACE_PATTERN.match(normalized)
        if not match:
            return None
        value = self._coerce_numeric_token(str(match.group(1)))
        if value < 0:
            raise ValueError(raw_value)
        return NormalizeResult(
            value=value,
            confidence=0.8 if approximate else 1.0,
            original=raw_value,
            needs_review=approximate,
            to_remarks=(f"Approximate surface: {raw_value}" if approximate else None),
        )

    def _normalize_surface_range_value(self, raw_value: str, field_name: str) -> NormalizeResult:
        normalized = _APPROXIMATE_PREFIX_PATTERN.sub("", raw_value).strip()
        range_match = _SURFACE_RANGE_PATTERN.match(normalized)
        if range_match:
            low = self._coerce_numeric_token(str(range_match.group(1)))
            high = self._coerce_numeric_token(str(range_match.group(2)))
            if low < 0 or high < 0:
                raise ValueError(raw_value)
            if low > high:
                low, high = high, low
            value = low if field_name == "surface_min" else high
            extra_key = "surface_max" if field_name == "surface_min" else "surface_min"
            return NormalizeResult(
                value=value,
                confidence=1.0,
                original=raw_value,
                extracted_extras={extra_key: high if extra_key == "surface_max" else low},
            )
        exact = self._normalize_surface_scalar_value(raw_value)
        if exact is None or exact.value is None:
            raise ValueError(raw_value)
        if not isinstance(exact.value, (int, float)):
            raise ValueError(raw_value)
        numeric_value = float(exact.value)
        extra_key = "surface_max" if field_name == "surface_min" else "surface_min"
        return NormalizeResult(
            value=numeric_value,
            confidence=exact.confidence,
            original=raw_value,
            needs_review=exact.needs_review,
            extracted_extras={extra_key: numeric_value},
            to_remarks=exact.to_remarks,
        )

    def _coerce_numeric_token(self, token: str) -> float:
        parsed = TypeParser.calculate_float_value(token)
        if parsed is None:
            raise ValueError(token)
        return float(parsed)

    def _normalize_beds_min_value(self, raw_value: str) -> NormalizeResult:
        normalized = str(raw_value or "").strip()
        if re.match(r"^\s*[FfTt]\s*\d+\s*$", normalized):
            return NormalizeResult(
                value=None,
                confidence=0.0,
                original=raw_value,
                needs_review=True,
                to_remarks=f"Beds value needs review: {raw_value}",
                extracted_extras={"candidate_pattern": normalized},
            )
        range_match = _INTEGER_RANGE_PATTERN.match(normalized)
        if range_match:
            low = int(range_match.group(1))
            high = int(range_match.group(2))
            if low > high:
                low, high = high, low
            return NormalizeResult(
                value=low,
                confidence=0.75,
                original=raw_value,
                needs_review=True,
                to_remarks=f"Bedroom range needs review: {raw_value}",
                extracted_extras={"candidate_max": high},
            )
        word_value = self._parse_word_number(normalized)
        if word_value is not None:
            return NormalizeResult(
                value=word_value,
                confidence=0.92,
                original=raw_value,
            )
        value = self._parse_integer_quantity_value(normalized)
        if value < 0:
            raise ValueError(raw_value)
        return NormalizeResult(
            value=value,
            confidence=1.0,
            original=raw_value,
        )

    def _normalize_floor_scalar_value(self, raw_value: str) -> NormalizeResult | None:
        normalized = str(raw_value or "").strip()
        if _GROUND_FLOOR_PATTERN.match(normalized):
            needs_review = "sur" in normalized.lower()
            return NormalizeResult(
                value=0,
                confidence=0.75 if needs_review else 1.0,
                original=raw_value,
                needs_review=needs_review,
                to_remarks=(
                    f"Raised ground floor needs review: {raw_value}" if needs_review else None
                ),
            )
        ordinal_match = _FLOOR_ORDINAL_PATTERN.match(normalized)
        if ordinal_match:
            value = int(ordinal_match.group(1))
            return NormalizeResult(
                value=value,
                confidence=1.0,
                original=raw_value,
            )
        word_value = self._parse_word_number(normalized)
        if word_value is not None:
            return NormalizeResult(
                value=word_value,
                confidence=0.9,
                original=raw_value,
            )
        return None

    def _normalize_floor_range_value(self, raw_value: str, field_name: str) -> NormalizeResult:
        text = str(raw_value or "").strip()
        range_match = _FLOOR_TEXT_RANGE_PATTERN.match(text) or _INTEGER_RANGE_PATTERN.match(text)
        if range_match:
            low = int(range_match.group(1))
            high = int(range_match.group(2))
            if low > high:
                low, high = high, low
            value = low if field_name == "floor_min" else high
            extra_key = "floor_max" if field_name == "floor_min" else "floor_min"
            return NormalizeResult(
                value=value,
                confidence=1.0,
                original=raw_value,
                extracted_extras={extra_key: high if extra_key == "floor_max" else low},
            )
        exact = self._normalize_floor_scalar_value(text)
        if exact is None or exact.value is None:
            raise ValueError(raw_value)
        if not isinstance(exact.value, (int, float)):
            raise ValueError(raw_value)
        numeric_value = int(exact.value)
        extra_key = "floor_max" if field_name == "floor_min" else "floor_min"
        return NormalizeResult(
            value=numeric_value,
            confidence=exact.confidence,
            original=raw_value,
            needs_review=exact.needs_review,
            extracted_extras={extra_key: numeric_value},
            to_remarks=exact.to_remarks,
        )

    # -- Context building --

    def _build_context(self, row: dict[str, Any]) -> RowContext:
        """Build cross-column context from the row.

        Extracts hints like wilaya from other columns to help
        normalizers make better decisions.
        """
        wilaya_hint: str | None = None
        action_hint: str | None = None
        type_hint: str | None = None

        for field_name, value in row.items():
            if not value:
                continue
            col_type = self.column_types.get(field_name, "unknown")

            if col_type in _WILAYA_TYPES:
                raw = str(value).strip()
                try:
                    code = int(raw)
                    if 1 <= code <= 58:
                        wilaya_hint = str(code).zfill(2)
                except ValueError:
                    pass

            elif col_type in _ACTION_TYPES:
                action_hint = str(value).strip().lower()

            elif col_type in _PROPERTY_TYPE_TYPES:
                type_hint = str(value).strip().lower()

        return RowContext(
            wilaya_hint=wilaya_hint,
            action_hint=action_hint,
            type_hint=type_hint,
            row_data={k: str(v) for k, v in row.items() if v is not None},
        )

    def _context_for_field(
        self,
        context: RowContext,
        field_name: str,
        col_type: str,
    ) -> RowContext:
        metadata = dict(context.metadata or {})
        metadata.update(dict(self.field_metadata.get(field_name, {}) or {}))
        metadata["field_name"] = field_name
        metadata["column_type"] = col_type
        return RowContext(
            wilaya_hint=context.wilaya_hint,
            action_hint=context.action_hint,
            type_hint=context.type_hint,
            row_data=dict(context.row_data or {}),
            metadata=metadata,
        )

    def _review_field_metadata(
        self,
        *,
        field_name: str,
        col_type: str,
        result: NormalizeResult,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "column_type": col_type,
            "extracted_extras": dict(result.extracted_extras),
            "source_header": str(
                self.field_metadata.get(field_name, {}).get("source_header", "") or ""
            ),
        }
        interpretation_candidates_raw = result.extracted_extras.get("interpretation_candidates", [])
        interpretation_candidates = (
            interpretation_candidates_raw if isinstance(interpretation_candidates_raw, list) else []
        )
        if interpretation_candidates:
            metadata["interpretation_candidates"] = [
                dict(candidate)
                for candidate in interpretation_candidates
                if isinstance(candidate, dict)
            ]
        ambiguity_reason_codes_raw = result.extracted_extras.get("price_ambiguity_reason_codes", [])
        ambiguity_reason_codes = (
            ambiguity_reason_codes_raw if isinstance(ambiguity_reason_codes_raw, list) else []
        )
        if ambiguity_reason_codes:
            metadata["price_ambiguity_reason_codes"] = [
                str(code) for code in ambiguity_reason_codes if str(code)
            ]
        phone_kind = str(result.extracted_extras.get("phone_kind", "") or "")
        if phone_kind:
            metadata["phone_kind"] = phone_kind
        return metadata


__all__ = [
    "NormalizationPipeline",
    "NormalizedRow",
    "ExtraConflict",
    "ReviewField",
    "REVIEW_THRESHOLD",
]
