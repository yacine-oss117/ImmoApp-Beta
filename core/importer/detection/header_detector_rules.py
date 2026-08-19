"""
Rules for header detection heuristics.
"""

from __future__ import annotations

import re

# Patterns that indicate header content
HEADER_KEYWORDS = {
    # French
    "nom",
    "prénom",
    "prenom",
    "telephone",
    "téléphone",
    "tel",
    "adresse",
    "email",
    "date",
    "prix",
    "budget",
    "type",
    "wilaya",
    "commune",
    "surface",
    "etage",
    "étage",
    # English
    "name",
    "phone",
    "address",
    "price",
    "city",
    "area",
    "floor",
    "rooms",
    "notes",
    # Arabic
    "اسم",
    "هاتف",
    "عنوان",
    "تاريخ",
    "سعر",
    "نوع",
}

# Patterns that indicate data content
DATA_PATTERNS = [
    re.compile(r"^\d{10}$"),  # Phone number
    re.compile(r"^\d+[\.,]?\d*$"),  # Number
    re.compile(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$"),  # Date
    re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"),  # Email
]
