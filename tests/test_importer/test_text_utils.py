from __future__ import annotations

from core.importer.normalizers.text_utils import canonicalize_text, strip_labels


def test_canonicalize_text_strips_french_accents() -> None:
    assert canonicalize_text("Béjaïa à côté d'Oran") == "bejaia a cote d'oran"


def test_canonicalize_text_converts_arabic_indic_digits() -> None:
    assert canonicalize_text("١٢٣٤٥٦٧٨٩٠") == "1234567890"


def test_canonicalize_text_handles_mixed_digit_families() -> None:
    assert canonicalize_text("budget 12٤۵") == "budget 1245"


def test_canonicalize_text_cleans_nbsp_zero_width_and_bom() -> None:
    assert canonicalize_text("\ufeffHydra\u200b\xa0Centre") == "hydra centre"


def test_canonicalize_text_removes_ascii_control_characters() -> None:
    assert canonicalize_text("prix\x00\x07 15\x1f000") == "prix 15000"


def test_canonicalize_text_replaces_smart_quotes_and_dashes() -> None:
    assert canonicalize_text("“Local” — centre") == '"local" - centre'


def test_canonicalize_text_collapses_whitespace() -> None:
    assert canonicalize_text("  Alger \n\t Centre   ") == "alger centre"


def test_canonicalize_text_empty_string() -> None:
    assert canonicalize_text("") == ""


def test_canonicalize_text_already_clean_text_is_stable() -> None:
    assert canonicalize_text("local commercial") == "local commercial"


def test_strip_labels_removes_known_prefix_label() -> None:
    assert strip_labels("Tél: 0555 12 34 56") == "0555 12 34 56"


def test_strip_labels_keeps_unknown_prefix() -> None:
    assert strip_labels("reference: local commercial") == "reference: local commercial"
