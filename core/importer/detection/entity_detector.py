"""
Entity type detector.

Detects whether a file contains client data or listing data based on column names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.importer.normalizers.text_utils import canonicalize_text, normalize_whitespace


@dataclass
class EntityTypeResult:
    """Result of entity type detection.

    Attributes:
        entity_type: Detected type ('client', 'listing', or None).
        confidence: Detection confidence 0.0-1.0.
        client_score: Number of client-indicative columns found.
        listing_score: Number of listing-indicative columns found.
    """

    entity_type: str | None
    confidence: float
    client_score: int = 0
    listing_score: int = 0


class EntityTypeDetector:
    """Detects whether file contains client or listing data.

    Uses column name analysis to determine entity type.
    This helps validate that users are importing to the correct destination.

    Example:
        detector = EntityTypeDetector()
        result = detector.detect(["Nom", "Téléphone", "Budget"])
        # result.entity_type == "client"
    """

    # Column names that indicate client data
    CLIENT_INDICATORS = {
        "phone",
        "telephone",
        "tel",
        "mobile",
        "téléphone",
        "budget",
        "client",
        "nom",
        "name",
        "contact",
        "demande",
        "recherche",
    }

    # Column names that indicate listing data
    LISTING_INDICATORS = {
        "surface",
        "superficie",
        "m2",
        "m²",
        "prix",
        "price",
        "prix de vente",
        "pieces",
        "pièces",
        "rooms",
        "chambres",
        "etage",
        "étage",
        "floor",
        "offre",
        "annonce",
        "reference",
        "référence",
    }

    def detect(self, columns: list[str]) -> EntityTypeResult:
        """Detect entity type from column names.

        Args:
            columns: List of column names from file.

        Returns:
            EntityTypeResult with detected type and confidence.
        """
        columns_lower = [_normalized_column_name(c) for c in columns]

        client_score = sum(
            1
            for c in columns_lower
            if any(_contains_indicator(c, ind) for ind in self.CLIENT_INDICATORS)
        )

        listing_score = sum(
            1
            for c in columns_lower
            if any(_contains_indicator(c, ind) for ind in self.LISTING_INDICATORS)
        )

        total = client_score + listing_score
        if total == 0:
            return EntityTypeResult(
                entity_type=None,
                confidence=0.0,
                client_score=0,
                listing_score=0,
            )

        if client_score > listing_score:
            confidence = client_score / total
            return EntityTypeResult(
                entity_type="client",
                confidence=confidence,
                client_score=client_score,
                listing_score=listing_score,
            )
        elif listing_score > client_score:
            confidence = listing_score / total
            return EntityTypeResult(
                entity_type="listing",
                confidence=confidence,
                client_score=client_score,
                listing_score=listing_score,
            )
        else:
            return EntityTypeResult(
                entity_type=None,
                confidence=0.5,
                client_score=client_score,
                listing_score=listing_score,
            )


# Backwards compatibility function
def detect_entity_type_from_columns(columns: list[str]) -> tuple[str | None, float]:
    """Detect entity type from column names (backwards compatible).

    Args:
        columns: List of column names.

    Returns:
        Tuple of (entity_type, confidence).
    """
    detector = EntityTypeDetector()
    result = detector.detect(columns)
    return result.entity_type, result.confidence


def _normalized_column_name(column_name: str) -> str:
    normalized = canonicalize_text(column_name).replace("²", "2")
    normalized = re.sub(r"[_/\\-]+", " ", normalized)
    return normalize_whitespace(normalized)


def _contains_indicator(column_name: str, indicator: str) -> bool:
    return (
        re.search(
            rf"\b{re.escape(_normalized_column_name(indicator))}\b",
            column_name,
        )
        is not None
    )
