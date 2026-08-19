from __future__ import annotations

import re
from pathlib import Path

UNQUALIFIED_DELETED_AT_RE = re.compile(r"(?<!\.)deleted_at\s+IS\s+NULL")


def test_hotspot_queries_use_qualified_deleted_at() -> None:
    files = [
        "server/services/matches.py",
        "server/services/listings.py",
        "server/services/duplicate_checker.py",
        "core/matcher/match_counter_demande.py",
        "core/data/client_repo_read.py",
        "core/data/listing_repo_read.py",
    ]
    offenders: list[str] = []
    for relative_path in files:
        text = Path(relative_path).read_text(encoding="utf-8")
        if UNQUALIFIED_DELETED_AT_RE.search(text):
            offenders.append(relative_path)
    assert not offenders, f"Use qualified aliases for deleted_at in hotspot SQL: {offenders}"
