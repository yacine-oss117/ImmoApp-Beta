"""
Property type normalizer.

Extracts property type and bedroom count from combined strings like "F3", "Villa", etc.
"""

from __future__ import annotations

import re

from core.importer.normalizers.base import NormalizeResult, RowContext
from core.importer.normalizers.text_utils import canonicalize_text

# Property type mappings (normalized name → canonical type)
# Includes common orthographic mistakes
TYPE_MAPPINGS: dict[str, str] = {
    # Apartments (with typos)
    "f1": "apartment",
    "f2": "apartment",
    "f3": "apartment",
    "f4": "apartment",
    "f5": "apartment",
    "f6": "apartment",
    "f7": "apartment",
    "appartement": "apartment",
    "apartement": "apartment",  # typo: missing 'p'
    "appartment": "apartment",  # typo: missing 'e'
    "appatement": "apartment",  # typo: missing 'r'
    "appartemnt": "apartment",  # typo: swapped 'nt'
    "appart": "apartment",
    "apartment": "apartment",
    "apt": "apartment",
    "app": "apartment",
    # Arabic apartments
    "شقة": "apartment",
    "شقه": "apartment",  # variant spelling
    # Studio
    "studio": "studio",
    "stuido": "studio",  # typo: swapped 'ui'
    "studoi": "studio",  # typo: swapped 'io'
    "duplex": "duplex",
    "triplex": "triplex",
    # Houses
    "villa": "villa",
    "فيلا": "villa",
    "فيللا": "villa",  # variant with double 'l'
    "maison": "house",
    "maisson": "house",  # typo: double 's'
    "mazon": "house",  # typo: z instead of s
    "house": "house",
    "منزل": "house",
    "niveau de villa": "villa_level",
    "niveau": "villa_level",
    "etage de villa": "villa_level",
    # Commercial
    "local": "commercial",
    "local commercial": "commercial",
    "locale": "commercial",  # typo: extra 'e'
    "locaux": "commercial",  # plural
    "bureau": "office",
    "burreau": "office",  # typo: double 'r'
    "bureaux": "office",  # plural
    "office": "office",
    "مكتب": "office",
    "magasin": "shop",
    "magasain": "shop",  # typo: swapped 'a'
    "boutique": "shop",
    "shop": "shop",
    "محل": "shop",
    "depot": "warehouse",
    "dépôt": "warehouse",
    "entrepot": "warehouse",
    "entrepôt": "warehouse",
    "hangar": "warehouse",
    "hanger": "warehouse",  # typo: 'e' instead of 'a'
    # Land
    "terrain": "land",
    "terran": "land",  # typo: missing 'i'
    "terrian": "land",  # typo: swapped 'ai'
    "land": "land",
    "lot": "land",
    "parcelle": "land",
    "أرض": "land",
    # Other
    "parking": "parking",
    "parkin": "parking",  # typo: missing 'g'
    "parkng": "parking",  # typo: missing 'i'
    "garage": "garage",
    "garag": "garage",  # typo: missing 'e'
    "cave": "basement",
    "sous-sol": "basement",
    "soussol": "basement",  # no hyphen
    "sous sol": "basement",  # space instead of hyphen
}
_SORTED_TYPE_KEYS = sorted(TYPE_MAPPINGS.keys(), key=len, reverse=True)

# Patterns to extract bedroom count
BEDROOM_PATTERNS = [
    # F3, F4, etc.
    re.compile(r"[Ff](\d+)"),
    # 3 chambres, 4 pieces
    re.compile(r"(\d+)\s*(?:chambres?|ch|pieces?|pcs?)", re.IGNORECASE),
    # 3 bedrooms
    re.compile(r"(\d+)\s*(?:bedrooms?|beds?|br)", re.IGNORECASE),
]


class PropertyTypeNormalizer:
    """Normalizer for property types.

    Handles formats like:
    - F3 → type=apartment, beds=3
    - Villa → type=villa
    - Appartement 4 pieces → type=apartment, beds=4
    - Studio → type=studio, beds=1
    """

    def normalize(self, value: str, context: RowContext | None = None) -> NormalizeResult:
        """Normalize a property type value.

        Args:
            value: Raw property type string.
            context: Optional row context.

        Returns:
            NormalizeResult with normalized type and extracted beds.
        """
        if not value or not value.strip():
            return NormalizeResult(
                value=None,
                confidence=1.0,
                original=value,
                needs_review=False,
            )

        original = value
        text = canonicalize_text(value)

        # Try to extract bedroom count first
        beds = self._extract_beds(text)

        # Try to match type
        property_type = None
        confidence = 0.0

        # Check for exact matches
        matched = self._match_type(text)
        if matched is not None:
            _pattern, property_type = matched
            confidence = 1.0

        # If no match, check for F-pattern (F3, F4, etc.)
        if not property_type:
            match = re.search(r"[Ff]\d+", text)
            if match:
                property_type = "apartment"
                confidence = 1.0

        # Handle studio special case
        if property_type == "studio" and beds is None:
            beds = 1

        if property_type:
            extras: dict[str, object] = {}
            if beds is not None:
                extras["beds"] = beds

            return NormalizeResult(
                value=property_type,
                confidence=confidence,
                original=original,
                needs_review=False,
                extracted_extras=extras,
            )

        # No match found - could be custom type
        return NormalizeResult(
            value=None,
            confidence=0.0,
            original=original,
            needs_review=True,
            to_remarks=f"Unknown property type: {original}",
        )

    def _extract_beds(self, text: str) -> int | None:
        """Extract bedroom count from text.

        Args:
            text: Lowercase text to search.

        Returns:
            Bedroom count or None if not found.
        """
        for pattern in BEDROOM_PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue

        return None

    def _match_type(self, text: str) -> tuple[str, str] | None:
        for pattern in _SORTED_TYPE_KEYS:
            if pattern in text:
                return pattern, TYPE_MAPPINGS[pattern]
        return None

    def get_type_display(self, property_type: str) -> str:
        """Get display name for property type.

        Args:
            property_type: Canonical type code.

        Returns:
            Human-readable display name.
        """
        display_names = {
            "apartment": "Appartement",
            "studio": "Studio",
            "duplex": "Duplex",
            "triplex": "Triplex",
            "villa": "Villa",
            "house": "Maison",
            "villa_level": "Niveau de Villa",
            "commercial": "Local Commercial",
            "office": "Bureau",
            "shop": "Magasin",
            "warehouse": "Dépôt",
            "land": "Terrain",
            "parking": "Parking",
            "garage": "Garage",
            "basement": "Sous-sol",
        }

        return display_names.get(property_type, property_type.title())
