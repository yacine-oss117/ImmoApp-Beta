from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.data import offer_repo_write


class _ExecuteResult:
    def __init__(self, rows: Sequence[dict[str, object]] | None = None) -> None:
        self._rows = list(rows or [])

    def fetchall(self) -> list[dict[str, object]]:
        return list(self._rows)


class _FakeSession:
    def __init__(
        self,
        *,
        lastrowid: int = 1,
        rowcount: int = 1,
        rows: Sequence[dict[str, object]] | None = None,
    ) -> None:
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self.rows = list(rows or [])
        self.sql_calls: list[tuple[str, tuple[object, ...] | list[object]]] = []

    def execute(
        self,
        sql: str,
        params: Sequence[object] | None = None,
    ) -> _ExecuteResult:
        normalized_params: tuple[object, ...] | list[object]
        if isinstance(params, list):
            normalized_params = list(params)
        else:
            normalized_params = tuple(params or ())
        self.sql_calls.append((sql, normalized_params))
        return _ExecuteResult(self.rows)


def _offer_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "apartment",
        "type_id": 1,
        "action": "sell",
        "action_id": 1,
        "status": "available",
        "wilaya": "16",
        "wilaya_id": 16,
        "location": "Hydra",
        "beds": 3,
        "surface": 120.0,
        "budget": 10_000_000,
        "furnished": "",
        "floor": 2,
        "elevator": True,
        "accessibility_supported": False,
        "price_negotiable": False,
        "price_flex_pct": 0.0,
        "remarks": "",
        "row_version": 1,
    }
    payload.update(overrides)
    return payload


def test_prepare_offer_values_keeps_explicit_negotiable_checkbox() -> None:
    prepared = offer_repo_write._prepare_offer_values(
        1,
        _offer_payload(price_negotiable=True, price_flex_pct=0.0),
    )

    assert prepared["price_negotiable"] == 1
    assert prepared["price_flex_pct"] == 0.0


def test_create_offer_uses_percentage_ratio_for_price_range(monkeypatch: Any) -> None:
    session = _FakeSession(lastrowid=99)
    monkeypatch.setattr(offer_repo_write, "populate_location_links", lambda *args, **kwargs: None)

    offer_repo_write.create_offer(session, 7, _offer_payload(price_flex_pct=10.0))

    sql, params = next(
        (call for call in session.sql_calls if "INSERT INTO offers" in call[0]),
        ("", ()),
    )
    assert "numrange((%s * (1 - %s))::numeric, (%s * (1 + %s))::numeric, '[]')" in sql
    assert params[-6] == 10.0
    assert params[-5] == 10_000_000
    assert params[-4] == 0.1
    assert params[-3] == 10_000_000
    assert params[-2] == 0.1
    assert params[-1] == 7


def test_insert_offers_batch_scales_price_flex_percent_in_sql(monkeypatch: Any) -> None:
    session = _FakeSession(rows=[{"id": 101, "wilaya_id": 16, "location": "Hydra"}])
    monkeypatch.setattr(
        offer_repo_write,
        "populate_location_links_batch",
        lambda *args, **kwargs: None,
    )

    inserted_ids = offer_repo_write.insert_offers_batch(
        session,
        [
            _offer_payload(
                listing_id=7,
                price_negotiable=True,
                price_flex_pct=10.0,
            )
        ],
    )

    assert inserted_ids == [101]
    sql, _params = next(
        (call for call in session.sql_calls if "INSERT INTO offers" in call[0]),
        ("", ()),
    )
    assert (
        "(i.budget::numeric * (1 - (i.price_flex_pct::double precision / 100.0)))::numeric" in sql
    )
    assert (
        "(i.budget::numeric * (1 + (i.price_flex_pct::double precision / 100.0)))::numeric" in sql
    )
