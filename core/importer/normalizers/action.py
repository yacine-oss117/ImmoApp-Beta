"""
Action normalizer for buy/sell/rent detection.

Handles client actions (buy/rent) and listing actions (sell/rent).
"""

from __future__ import annotations

from core.importer.detection.entity_detector import (
    detect_entity_type_from_columns as _detect_entity_type_from_columns,
)
from core.importer.normalizers.base import NormalizeResult, RowContext
from core.importer.normalizers.text_utils import canonicalize_text

# Action mappings (normalized text → canonical action)
# Includes common orthographic mistakes and missing accents
ACTION_MAPPINGS: dict[str, str] = {
    # Buy / Purchase (for clients)
    "buy": "buy",
    "achat": "buy",
    "acheter": "buy",
    "achete": "buy",
    "achter": "buy",  # typo: missing 'e'
    "achetee": "buy",  # typo: double 'e'
    "acquisition": "buy",
    "aquisition": "buy",  # typo: missing 'c'
    "شراء": "buy",
    "للشراء": "buy",
    # Sell (for listings)
    "sell": "sell",
    "vente": "sell",
    "vendre": "sell",
    "a vendre": "sell",  # without accent (à → a) - handled by _normalize_text
    "avendre": "sell",  # no space
    "pour vente": "sell",
    "en vente": "sell",
    "للبيع": "sell",
    "بيع": "sell",
    # Rent (for both clients and listings)
    "rent": "rent",
    "location": "rent",
    "loction": "rent",  # typo: missing 'a'
    "loocation": "rent",  # typo: double 'o'
    "locaton": "rent",  # typo: missing 'i'
    "louer": "rent",
    "a louer": "rent",  # without accent (à → a) - handled by _normalize_text
    "alouer": "rent",  # no space
    "pour location": "rent",
    "en location": "rent",
    "للكراء": "rent",
    "كراء": "rent",
    "ايجار": "rent",
    "للإيجار": "rent",
    "الايجار": "rent",
}
_SORTED_ACTION_KEYS = sorted(ACTION_MAPPINGS.keys(), key=len, reverse=True)

# Valid actions per entity type
VALID_ACTIONS = {
    "client": {"buy", "rent"},  # demandes
    "listing": {"sell", "rent"},  # offres
}


class ActionNormalizer:
    """Normalizer for action types (buy/sell/rent).

    Handles formats like:
    - "Vente" → sell
    - "Achat" → buy
    - "Location" → rent
    - "للبيع" → sell
    """

    def __init__(self, entity_type: str | None = None) -> None:
        """Initialize action normalizer.

        Args:
            entity_type: Optional entity type ('client' or 'listing')
                        to validate action is appropriate.
        """
        self.entity_type = entity_type

    def normalize(self, value: str, context: RowContext | None = None) -> NormalizeResult:
        """Normalize an action value.

        Args:
            value: Raw action string.
            context: Optional row context.

        Returns:
            NormalizeResult with normalized action.
        """
        if not value or not value.strip():
            return NormalizeResult(
                value=None,
                confidence=1.0,
                original=value,
                needs_review=True,
                to_remarks="Action not specified",
            )

        original = value
        text = canonicalize_text(value)

        # Try exact match
        if text in ACTION_MAPPINGS:
            action = ACTION_MAPPINGS[text]
            return self._validate_action(action, original)

        # Try partial match
        for pattern in _SORTED_ACTION_KEYS:
            action = ACTION_MAPPINGS[pattern]
            if pattern in text:
                return self._validate_action(action, original, confidence=0.9)

        # No match found
        return NormalizeResult(
            value=None,
            confidence=0.0,
            original=original,
            needs_review=True,
            to_remarks=f"Unknown action: {original}",
        )

    def _validate_action(
        self,
        action: str,
        original: str,
        confidence: float = 1.0,
    ) -> NormalizeResult:
        """Validate action against entity type.

        Args:
            action: Canonical action (buy/sell/rent).
            original: Original input.
            confidence: Base confidence.

        Returns:
            NormalizeResult, possibly with warnings.
        """
        extras: dict[str, object] = {}

        # Validate against entity type if specified
        if self.entity_type:
            valid_actions = VALID_ACTIONS.get(self.entity_type, set())
            if action not in valid_actions:
                # Wrong action for entity type!
                extras["entity_mismatch"] = True
                extras["expected_entity"] = "listing" if action == "sell" else "client"
                return NormalizeResult(
                    value=action,
                    confidence=0.5,
                    original=original,
                    needs_review=True,
                    extracted_extras=extras,
                    to_remarks=(
                        f"Action '{action}' is not valid for {self.entity_type}. "
                        f"Expected: {valid_actions}"
                    ),
                )

        return NormalizeResult(
            value=action,
            confidence=confidence,
            original=original,
            needs_review=False,
            extracted_extras=extras,
        )


def detect_entity_type_from_columns(columns: list[str]) -> tuple[str | None, float]:
    """Backwards-compatible wrapper for the shared entity detector."""
    return _detect_entity_type_from_columns(columns)
