from __future__ import annotations

from core.data.read_helpers import build_people_search_conditions


def test_people_search_uses_db_side_hash_function():
    where_sql, params = build_people_search_conditions(
        search="Märçô",
        person_alias="c",
        join_fields=("o.location", "o.remarks"),
    )

    assert "immoapp_hash_trigrams(%s)" in where_sql
    assert "family_name_search_idx &&" in where_sql
    assert "phone_search_idx &&" in where_sql
    assert params[0] == "Märçô"
    assert params[1] == "Märçô"
