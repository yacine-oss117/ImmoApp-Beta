"""
Boolean field normalizer.

Handles boolean fields like elevator, parking, VIP, etc.
"""

from __future__ import annotations

from core.importer.normalizers.base import NormalizeResult, RowContext
from core.importer.normalizers.text_utils import canonicalize_text

# Boolean value mappings
TRUE_VALUES = {
    # French
    "oui",
    "o",
    "yes",
    "y",
    "vrai",
    "true",
    "1",
    # Arabic
    "نعم",
    "اه",
    "ايه",
    # Symbols
    "✓",
    "✔",
    "☑",
}

FALSE_VALUES = {
    # French
    "non",
    "n",
    "no",
    "faux",
    "false",
    "0",
    # Arabic
    "لا",
    "لأ",
    # Explicit negatives
    "aucun",
    "sans",
}

# N/A indicators - these mean "not applicable", not "no"
# They should return None, not False
NULL_VALUES = {
    "-",
    "—",
    "na",
    "n/a",
    "non applicable",
    "non renseigne",
    "non renseigné",
    "vide",
    "empty",
    "null",
    "none",
    "any",
    "indifferent",
    "peu importe",
}

_SEMI_VALUES = {
    "semi",
    "semi meuble",
    "semi meublé",
    "semi-furnished",
}


class BooleanNormalizer:
    """Normalizer for boolean fields.

    Handles formats like:
    - "Oui" / "Non"
    - "Yes" / "No"
    - "1" / "0"
    - "✓" / ""
    - Arabic نعم / لا
    """

    def __init__(self, default_value: bool | None = None) -> None:
        """Initialize boolean normalizer.

        Args:
            default_value: Default value for empty or unknown values.
        """
        self.default_value = default_value

    def normalize(self, value: str, context: RowContext | None = None) -> NormalizeResult:
        """Normalize a boolean value.

        Args:
            value: Raw boolean string.
            context: Optional row context.

        Returns:
            NormalizeResult with normalized boolean.
        """
        if not value or not value.strip():
            return NormalizeResult(
                value=self.default_value,
                confidence=1.0 if self.default_value is not None else 0.5,
                original=value,
                needs_review=self.default_value is None,
            )

        original = value
        text = canonicalize_text(value)

        # Check for N/A values first - these mean "not applicable", not "no"
        if text in NULL_VALUES:
            return NormalizeResult(
                value=None,
                confidence=1.0,
                original=original,
                needs_review=False,  # Explicit N/A is valid
            )

        if text in _SEMI_VALUES:
            return NormalizeResult(
                value=None,
                confidence=0.4,
                original=original,
                needs_review=True,
                to_remarks=f"Semi-furnished value needs review: {original}",
            )

        if text == "x":
            return NormalizeResult(
                value=None,
                confidence=0.7,
                original=original,
                needs_review=True,
                to_remarks="Ambiguous 'x' - could mean checked or unknown",
            )

        # Check for true values
        if text in TRUE_VALUES:
            return NormalizeResult(
                value=True,
                confidence=1.0,
                original=original,
            )

        # Check for false values
        if text in FALSE_VALUES:
            return NormalizeResult(
                value=False,
                confidence=1.0,
                original=original,
            )

        # Try numeric interpretation
        try:
            num = float(text)
            return NormalizeResult(
                value=num > 0,
                confidence=0.8,
                original=original,
            )
        except ValueError:
            pass

        # Unknown value
        return NormalizeResult(
            value=self.default_value,
            confidence=0.0,
            original=original,
            needs_review=True,
            to_remarks=f"Unknown boolean value: {original}",
        )

    def format_display(self, value: bool | None, lang: str = "fr") -> str:
        """Format boolean for display.

        Args:
            value: Boolean value.
            lang: Language for display (fr, ar, en).

        Returns:
            Display string.
        """
        if value is None:
            return "-"

        if lang == "ar":
            return "نعم" if value else "لا"
        elif lang == "en":
            return "Yes" if value else "No"
        else:  # French default
            return "Oui" if value else "Non"
