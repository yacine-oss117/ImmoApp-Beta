from __future__ import annotations

from core.data.match_cache_read import get_cached_counts_with_meta_for_ids


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _Session:
    def execute(self, _sql: str, _params):
        rows = [
            {"client_id": 1, "count": 7, "computed_at": None, "is_dirty": 0},
            {"client_id": 2, "count": 3, "computed_at": None, "is_dirty": 1},
        ]
        return _Result(rows)


def test_get_cached_counts_with_meta_marks_fresh_stale_missing() -> None:
    counts, meta = get_cached_counts_with_meta_for_ids(_Session(), [1, 2, 3])
    assert counts == {1: 7, 2: 3}
    assert meta[1]["status"] == "fresh"
    assert meta[2]["status"] == "stale"
    assert meta[3]["status"] == "missing"
