from __future__ import annotations

from pathlib import Path


def test_match_partition_rollout_declares_hardened_agency_columns() -> None:
    text = Path("server/pg/match_partitions.py").read_text(encoding="utf-8")
    assert "agency_id BIGINT NOT NULL" in text
    assert "FOREIGN KEY (agency_id, demande_id) REFERENCES demandes(agency_id, id)" in text
    assert "FOREIGN KEY (agency_id, offer_id) REFERENCES offers(agency_id, id)" in text
    assert "FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)" in text


def test_match_partition_rollout_reapplies_agency_defaults_and_not_null() -> None:
    text = Path("server/pg/match_partitions.py").read_text(encoding="utf-8")
    assert "ALTER COLUMN agency_id SET DEFAULT" in text
    assert "ALTER COLUMN agency_id SET NOT NULL" in text
