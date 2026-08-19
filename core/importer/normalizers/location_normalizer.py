"""
Location normalizer with fuzzy matching.

Uses master data to match locations to commune codes.
"""

from __future__ import annotations

from typing import Any

from core.importer.normalizers.base import NormalizeResult, RowContext
from core.importer.normalizers.location_data import load_aliases, load_communes, load_wilayas
from core.importer.normalizers.location_text import (
    extract_location_candidates,
    normalize_text,
)
from core.importer.normalizers.text_utils import canonicalize_text


class LocationNormalizer:
    """Normalizer for locations using fuzzy matching."""

    def __init__(self, min_confidence: float = 0.7) -> None:
        self.min_confidence = min_confidence
        self._wilayas: dict[str, Any] = load_wilayas()
        self._communes: dict[str, Any] = load_communes()
        self._aliases: dict[str, str] = load_aliases()
        self._build_lookup_tables()

    def _build_lookup_tables(self) -> None:
        self._wilaya_by_name: dict[str, str] = {}
        for code, data in self._wilayas.items():
            fr_name = normalize_text(str(data.get("fr", "")))
            if fr_name:
                self._wilaya_by_name[fr_name] = code

            ar_name = str(data.get("ar", ""))
            if ar_name:
                self._wilaya_by_name[ar_name] = code

            aliases = data.get("aliases", [])
            for alias in list(aliases):
                self._wilaya_by_name[normalize_text(str(alias))] = code

        self._commune_by_name: dict[str, tuple[str, str]] = {}
        for wilaya_code, data in self._communes.items():
            communes = list(data.get("communes", []))
            for commune in communes:
                commune_code = str(commune.get("code", ""))
                fr_name = normalize_text(str(commune.get("fr", "")))
                if fr_name and commune_code:
                    self._commune_by_name[fr_name] = (commune_code, wilaya_code)

                commune_aliases = commune.get("aliases", [])
                for alias in list(commune_aliases):
                    norm_alias = normalize_text(str(alias))
                    if norm_alias:
                        self._commune_by_name[norm_alias] = (commune_code, wilaya_code)

    def normalize(self, value: str, context: RowContext | None = None) -> NormalizeResult:
        """Normalize a location value."""
        if not value or not value.strip():
            return NormalizeResult(
                value=None,
                confidence=1.0,
                original=value,
                needs_review=False,
            )

        original = value
        candidates = extract_location_candidates(canonicalize_text(value))

        for candidate in candidates:
            normalized = normalize_text(candidate)
            if not normalized:
                continue

            if normalized in self._aliases:
                commune_code = self._aliases[normalized]
                return NormalizeResult(
                    value=commune_code,
                    confidence=1.0,
                    original=original,
                    needs_review=False,
                    extracted_extras={"match_type": "alias"},
                )

            if normalized in self._commune_by_name:
                commune_code, wilaya_code = self._commune_by_name[normalized]

                if context and context.wilaya_hint:
                    if context.wilaya_hint != wilaya_code:
                        return NormalizeResult(
                            value=commune_code,
                            confidence=0.7,
                            original=original,
                            needs_review=True,
                            extracted_extras={
                                "match_type": "commune_wilaya_mismatch",
                                "expected_wilaya": context.wilaya_hint,
                                "found_wilaya": wilaya_code,
                            },
                        )

                return NormalizeResult(
                    value=commune_code,
                    confidence=1.0,
                    original=original,
                    needs_review=False,
                    extracted_extras={
                        "match_type": "exact_commune",
                        "wilaya_code": wilaya_code,
                    },
                )

            if normalized in self._wilaya_by_name:
                wilaya_code = self._wilaya_by_name[normalized]
                return NormalizeResult(
                    value=wilaya_code,
                    confidence=0.9,
                    original=original,
                    needs_review=False,
                    extracted_extras={
                        "match_type": "wilaya",
                        "is_wilaya": True,
                    },
                )

        if candidates:
            first_normalized = normalize_text(candidates[0])
            fuzzy_result = self._fuzzy_match(first_normalized, context)
            if fuzzy_result:
                return fuzzy_result

        return NormalizeResult(
            value=None,
            confidence=0.0,
            original=original,
            needs_review=True,
            to_remarks=f"Unknown location: {original}",
        )

    def _fuzzy_match(self, normalized: str, context: RowContext | None) -> NormalizeResult | None:
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            return None

        commune_names = list(self._commune_by_name.keys())
        if commune_names:
            result = process.extractOne(
                normalized,
                commune_names,
                scorer=fuzz.ratio,
                score_cutoff=70,
            )

            if result:
                match_name, score, _ = result
                commune_code, wilaya_code = self._commune_by_name[match_name]
                confidence = score / 100.0

                return NormalizeResult(
                    value=commune_code,
                    confidence=confidence,
                    original=normalized,
                    needs_review=confidence < self.min_confidence,
                    extracted_extras={
                        "match_type": "fuzzy_commune",
                        "matched_name": match_name,
                        "wilaya_code": wilaya_code,
                    },
                )

        wilaya_names = list(self._wilaya_by_name.keys())
        if wilaya_names:
            result = process.extractOne(
                normalized,
                wilaya_names,
                scorer=fuzz.ratio,
                score_cutoff=70,
            )

            if result:
                match_name, score, _ = result
                wilaya_code = self._wilaya_by_name[match_name]
                confidence = score / 100.0

                return NormalizeResult(
                    value=wilaya_code,
                    confidence=confidence,
                    original=normalized,
                    needs_review=confidence < self.min_confidence,
                    extracted_extras={
                        "match_type": "fuzzy_wilaya",
                        "matched_name": match_name,
                        "is_wilaya": True,
                    },
                )

        return None

    def get_wilaya_name(self, code: str) -> str | None:
        wilaya = self._wilayas.get(code)
        if wilaya:
            return str(wilaya.get("fr", ""))
        return None

    def get_commune_name(self, code: str) -> str | None:
        if len(code) >= 5:
            wilaya_code = code[:2]
            data = self._communes.get(wilaya_code)
            if data:
                communes_list = list(data.get("communes", []))
                for commune in communes_list:
                    if commune.get("code") == code:
                        return str(commune.get("fr", ""))
        return None


__all__ = ["LocationNormalizer"]
