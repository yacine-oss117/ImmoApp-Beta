"""Shared importer security limits and guard helpers."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from functools import lru_cache


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_v, min(max_v, value))


@dataclass(frozen=True)
class ImportSecurityLimits:
    preview_limit_default: int
    preview_limit_max: int
    skip_rows_max: int
    max_rows: int
    max_columns: int
    max_header_chars: int
    max_cell_chars: int
    max_sheets: int
    max_archive_entries: int
    max_archive_uncompressed_bytes: int
    max_archive_compression_ratio: int
    max_review_items_emergency: int
    max_review_groups_emergency: int
    max_review_rows: int
    max_duplicate_candidates: int
    max_mapping_fields: int
    max_correction_rows: int
    max_decisions: int
    sniff_bytes: int


@lru_cache(maxsize=1)
def import_security_limits() -> ImportSecurityLimits:
    """Return process-cached importer limits from environment configuration.

    Environment changes do not hot-reload into a running process. Apply new values by restarting
    the process; tests may use ``cache_clear()`` as a restart-equivalent seam.
    """
    max_rows = _env_int("IMMOAPP_IMPORT_MAX_ROWS", 20000, min_v=100, max_v=200000)
    max_review_items_emergency = _env_int(
        "IMMOAPP_IMPORT_MAX_REVIEW_ITEMS_EMERGENCY",
        _env_int(
            "IMMOAPP_IMPORT_MAX_REVIEW_ROWS",
            min(max_rows * 2, 100000),
            min_v=100,
            max_v=200000,
        ),
        min_v=100,
        max_v=200000,
    )
    max_review_groups_emergency = _env_int(
        "IMMOAPP_IMPORT_MAX_REVIEW_GROUPS_EMERGENCY",
        min(max_rows, 50000),
        min_v=100,
        max_v=200000,
    )
    return ImportSecurityLimits(
        preview_limit_default=_env_int(
            "IMMOAPP_IMPORT_PREVIEW_LIMIT_DEFAULT", 20, min_v=1, max_v=100
        ),
        preview_limit_max=_env_int("IMMOAPP_IMPORT_PREVIEW_LIMIT_MAX", 100, min_v=10, max_v=500),
        skip_rows_max=_env_int("IMMOAPP_IMPORT_SKIP_ROWS_MAX", 200, min_v=0, max_v=2000),
        max_rows=max_rows,
        max_columns=_env_int("IMMOAPP_IMPORT_MAX_COLUMNS", 128, min_v=8, max_v=512),
        max_header_chars=_env_int("IMMOAPP_IMPORT_MAX_HEADER_CHARS", 128, min_v=16, max_v=512),
        max_cell_chars=_env_int("IMMOAPP_IMPORT_MAX_CELL_CHARS", 8192, min_v=128, max_v=65536),
        max_sheets=_env_int("IMMOAPP_IMPORT_MAX_SHEETS", 5, min_v=1, max_v=32),
        max_archive_entries=_env_int("IMMOAPP_IMPORT_MAX_ARCHIVE_ENTRIES", 64, min_v=4, max_v=2048),
        max_archive_uncompressed_bytes=_env_int(
            "IMMOAPP_IMPORT_MAX_ARCHIVE_UNCOMPRESSED_BYTES",
            100 * 1024 * 1024,
            min_v=1024 * 1024,
            max_v=1024 * 1024 * 1024,
        ),
        max_archive_compression_ratio=_env_int(
            "IMMOAPP_IMPORT_MAX_ARCHIVE_COMPRESSION_RATIO", 25, min_v=2, max_v=200
        ),
        max_review_items_emergency=max_review_items_emergency,
        max_review_groups_emergency=max_review_groups_emergency,
        max_review_rows=max_review_items_emergency,
        max_duplicate_candidates=_env_int(
            "IMMOAPP_IMPORT_MAX_DUPLICATE_CANDIDATES", 5, min_v=1, max_v=20
        ),
        max_mapping_fields=_env_int("IMMOAPP_IMPORT_MAX_MAPPING_FIELDS", 128, min_v=8, max_v=512),
        max_correction_rows=_env_int(
            "IMMOAPP_IMPORT_MAX_CORRECTION_ROWS", 2000, min_v=100, max_v=20000
        ),
        max_decisions=_env_int("IMMOAPP_IMPORT_MAX_DECISIONS", 2000, min_v=100, max_v=20000),
        sniff_bytes=_env_int("IMMOAPP_IMPORT_SNIFF_BYTES", 8192, min_v=512, max_v=65536),
    )


def reload_import_security_limits() -> ImportSecurityLimits:
    """Explicitly refresh process-cached importer limits from the current environment."""
    import_security_limits.cache_clear()
    return import_security_limits()


def import_security_limits_snapshot() -> dict[str, object]:
    """Return a serializable snapshot of the live cached importer limit policy."""
    return {
        **asdict(import_security_limits()),
        "cache_policy": "process_cached_until_reload_or_restart",
        "reload_supported": True,
    }


def ensure_import_row_limit(row_count: int) -> None:
    if row_count > import_security_limits().max_rows:
        raise ValueError(
            f"Import file exceeds the maximum supported row count ({import_security_limits().max_rows})."
        )


def normalize_header_cells(values: list[str]) -> list[str]:
    limits = import_security_limits()
    trimmed = _trim_trailing_empty(values)
    if len(trimmed) > limits.max_columns:
        raise ValueError(
            f"Import file exceeds the maximum supported column count ({limits.max_columns})."
        )
    normalized: list[str] = []
    for index, value in enumerate(trimmed):
        header = (value or "").strip()
        if len(header) > limits.max_header_chars:
            raise ValueError(
                f"Import header exceeds the maximum supported length ({limits.max_header_chars})."
            )
        normalized.append(header or f"Column_{index + 1}")
    return normalized


def normalize_row_cells(values: list[str], *, expected_cols: int | None = None) -> list[str]:
    limits = import_security_limits()
    trimmed = _trim_trailing_empty(values)
    if len(trimmed) > limits.max_columns:
        raise ValueError(
            f"Import file exceeds the maximum supported column count ({limits.max_columns})."
        )
    normalized: list[str] = []
    for value in trimmed:
        text = (value or "").strip()
        if len(text) > limits.max_cell_chars:
            raise ValueError(
                f"Import cell exceeds the maximum supported length ({limits.max_cell_chars})."
            )
        normalized.append(text)
    if expected_cols is not None and expected_cols > 0:
        if len(normalized) >= expected_cols:
            return normalized[:expected_cols]
        return normalized + [""] * (expected_cols - len(normalized))
    return normalized


def _trim_trailing_empty(values: list[str]) -> list[str]:
    trimmed = list(values)
    while trimmed and not (trimmed[-1] or "").strip():
        trimmed.pop()
    return trimmed


__all__ = [
    "ImportSecurityLimits",
    "ensure_import_row_limit",
    "import_security_limits",
    "import_security_limits_snapshot",
    "normalize_header_cells",
    "normalize_row_cells",
    "reload_import_security_limits",
]
