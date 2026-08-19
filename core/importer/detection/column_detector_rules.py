"""
Rules and helpers for column type detection.
"""

from __future__ import annotations

import re
import unicodedata

# Header patterns for each field type
HEADER_PATTERNS: dict[str, list[str]] = {
    "phone": [
        "phone",
        "tel",
        "telephone",
        "mobile",
        "gsm",
        "téléphone",
        "portable",
        "numero",
        "numéro",
        "هاتف",
        "رقم",
    ],
    "price": [
        "price",
        "prix",
        "budget",
        "montant",
        "cout",
        "coût",
        "سعر",
        "ثمن",
        "مبلغ",
    ],
    "location": [
        "location",
        "lieu",
        "commune",
        "quartier",
        "adresse",
        "address",
        "sector",
        "secteur",
        "موقع",
        "عنوان",
    ],
    "wilaya": [
        "wilaya",
        "ville",
        "city",
        "region",
        "ولاية",
    ],
    "name": [
        "name",
        "nom",
        "client",
        "proprietaire",
        "propriétaire",
        "contact",
        "اسم",
        "صاحب",
    ],
    "email": [
        "email",
        "mail",
        "e-mail",
        "courriel",
        "بريد",
    ],
    "type": [
        "type",
        "kind",
        "property",
        "bien",
        "نوع",
    ],
    "action": [
        "action",
        "operation",
        "transaction",
        "عملية",
    ],
    "surface": [
        "surface",
        "superficie",
        "area",
        "m2",
        "m²",
        "مساحة",
    ],
    "rooms": [
        "rooms",
        "pieces",
        "pièces",
        "chambres",
        "beds",
        "غرف",
    ],
    "floor": [
        "floor",
        "etage",
        "étage",
        "niveau",
        "طابق",
    ],
    "elevator": [
        "elevator",
        "ascenseur",
        "lift",
        "مصعد",
    ],
    "parking": [
        "parking",
        "garage",
        "stationnement",
        "موقف",
    ],
    "accessibility_required": [
        "accessibility",
        "accessible",
        "handicap",
        "pmr",
        "mobilite reduite",
    ],
    "accessibility_supported": [
        "accessibility_supported",
        "accessible",
        "pmr",
        "handicap",
    ],
    "price_negotiable": [
        "negotiable",
        "negociable",
        "prix negociable",
        "price_negotiable",
    ],
    "date": [
        "date",
        "created",
        "updated",
        "تاريخ",
    ],
    "notes": [
        "notes",
        "remarques",
        "remarques additionnelles",
        "remarks",
        "commentaire",
        "observation",
        "tags",
        "labels",
        "tags labels",
        "ملاحظات",
    ],
}

# Value patterns for type inference from content
VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "phone": re.compile(r"^[\d\s\-\+\(\)]{8,15}$"),
    "price": re.compile(r"^\d+[\d\s\.,]*(?:M|millions?|DA|DZD)?$", re.IGNORECASE),
    "email": re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"),
    "date": re.compile(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$"),
}

FIELD_MAPPINGS = {
    "phone": "phone",
    "price": "budget",
    "location": "commune_id",
    "wilaya": "wilaya_id",
    "name": "name",
    "email": "email",
    "type": "property_type",
    "action": "action",
    "surface": "surface",
    "rooms": "rooms",
    "floor": "floor",
    "accessibility_required": "accessibility_required",
    "accessibility_supported": "accessibility_supported",
    "price_negotiable": "price_negotiable",
    "notes": "remarks",
}


def normalize_text(text: str) -> str:
    """Normalize text for matching."""
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def normalize_header_phrase(text: str) -> str:
    """Normalize a header into a stable token phrase."""
    normalized = normalize_text(text)
    normalized = re.sub(r"[()\\[\\]{}]+", " ", normalized)
    normalized = re.sub(r"[/|,_\\-]+", " ", normalized)
    normalized = re.sub(r"\\s+", " ", normalized)
    return normalized.strip()


def tokenize_header(text: str) -> tuple[str, ...]:
    """Split a normalized header into comparable tokens."""
    phrase = normalize_header_phrase(text)
    if not phrase:
        return ()
    return tuple(token for token in phrase.split(" ") if token)
