"""
Shared validation patterns for import validation.
"""

from __future__ import annotations

import re

# Patterns that indicate potential injection attempts
DANGEROUS_PATTERNS = [
    r"--",  # SQL comment
    r"/\*",  # SQL block comment start
    r"\*/",  # SQL block comment end
    r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b",
    r"(?i)\b(UNION|EXEC|EXECUTE|XP_|SP_)\b",
    r"(?i)\b(OR|AND)\s+\d+\s*=\s*\d+",  # OR 1=1 pattern
]

_compiled_patterns: list[re.Pattern[str]] | None = None


def get_dangerous_patterns() -> list[re.Pattern[str]]:
    """Get compiled regex patterns (cached)."""
    global _compiled_patterns
    if _compiled_patterns is None:
        _compiled_patterns = [re.compile(p) for p in DANGEROUS_PATTERNS]
    return _compiled_patterns
