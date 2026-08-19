from __future__ import annotations

from pathlib import Path


def test_notifications_insert_wraps_payload_with_jsonb() -> None:
    src = Path("server/services/notifications_mutations.py").read_text(encoding="utf-8")
    assert "from psycopg.types.json import Jsonb" in src
    assert "Jsonb(payload)" in src
