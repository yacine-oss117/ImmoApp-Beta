"""
Location text normalization helpers.
"""

from __future__ import annotations

import re

from core.importer.normalizers.text_utils import normalize_whitespace, strip_accents


def normalize_text(text: str) -> str:
    """Normalize text for matching."""
    if not text:
        return ""

    text = normalize_whitespace(text.lower())

    prefixes = ["el ", "el-", "al ", "al-", "les "]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break

    text = strip_accents(text)
    text = text.replace("'", "").replace("-", " ").replace("_", " ")

    return normalize_whitespace(text)


def extract_location_candidates(text: str) -> list[str]:
    """Extract location candidates from complex input."""
    if not text:
        return []

    candidates: list[str] = []
    original = text.strip()

    candidates.append(original)

    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        candidates.extend(parts)

    paren_match = re.match(r"^([^(]+)\s*\(([^)]+)\)", text)
    if paren_match:
        candidates.append(paren_match.group(1).strip())
        candidates.append(paren_match.group(2).strip())

    postal_match = re.match(r"^\d{5}\s+(.+)$", text)
    if postal_match:
        candidates.append(postal_match.group(1).strip())

    arabic_parts = re.findall(r"[\u0600-\u06FF]+", text)
    latin_parts = re.findall(r"[a-zA-ZàâäéèêëîïôùûüçÀÂÄÉÈÊËÎÏÔÙÛÜÇ]+", text)
    candidates.extend(arabic_parts)
    candidates.extend(latin_parts)

    seen: set[str] = set()
    unique_candidates: list[str] = []
    for candidate in candidates:
        candidate_key = candidate.lower().strip()
        if candidate_key and candidate_key not in seen:
            seen.add(candidate_key)
            unique_candidates.append(candidate.strip())

    return unique_candidates
