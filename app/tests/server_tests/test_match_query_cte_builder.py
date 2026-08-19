from __future__ import annotations

from core.matcher.match_query_cte import build_match_cte


def test_match_cte_uses_two_stage_dedup() -> None:
    cte = build_match_cte(select_cols="d.id as demande_id, o.id as offer_id")
    assert "WITH raw_pairs AS" in cte.sql
    assert "SELECT DISTINCT * FROM raw_pairs" in cte.sql


def test_match_cte_param_alignment_for_filtered_queries() -> None:
    cte = build_match_cte(demande_ids=[1, 2], offer_ids=[10, 11], select_cols="o.id as offer_id")
    # Parameter list must align exactly with SQL placeholders.
    assert cte.sql.count("%s") == len(cte.params)
    # Filtered query should carry both demande and offer id arrays.
    assert [1, 2] in cte.params
    assert [10, 11] in cte.params
