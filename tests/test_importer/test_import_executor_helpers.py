from __future__ import annotations

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.services import import_executor_helpers


def test_insert_batch_routes_demandes_to_batch_writer(monkeypatch) -> None:
    captured: dict[str, object] = {}
    dirty_clients: list[int] = []

    monkeypatch.setattr(
        import_executor_helpers,
        "normalize_demande_batch",
        lambda rows: list(rows),
    )
    monkeypatch.setattr(
        import_executor_helpers,
        "resolve_lookup_fields",
        lambda _session, row: {
            **row,
            "type_id": 1,
            "type": "apartment",
            "action_id": 1,
            "action": "buy",
            "wilaya_id": 16,
            "wilaya": "Alger",
        },
    )
    monkeypatch.setattr(
        import_executor_helpers,
        "_enforce_strict_demande_fields",
        lambda _row: None,
    )
    monkeypatch.setattr(
        import_executor_helpers.demande_write,
        "insert_demandes_batch",
        lambda _session, rows: _capture_batch_rows(captured, rows),
    )
    monkeypatch.setattr(
        import_executor_helpers,
        "mark_client_dirty",
        lambda _session, client_id: dirty_clients.append(int(client_id)),
    )

    demande_ids: set[int] = set()
    demande_client_ids: set[int] = set()
    result = import_executor_helpers.insert_batch(
        write_session=object(),
        entity_type="demande",
        batch_rows=[
            {
                "client_id": 11,
                "type": "apartment",
                "action": "buy",
                "wilaya": "16",
                "locations": "Hydra",
                "budget_min": 1,
                "budget_max": 2,
                "surface_min": 3,
                "surface_max": 4,
                "beds_min": 1,
            },
            {
                "client_id": 12,
                "type": "apartment",
                "action": "buy",
                "wilaya": "16",
                "locations": "El Biar",
                "budget_min": 1,
                "budget_max": 2,
                "surface_min": 3,
                "surface_max": 4,
                "beds_min": 1,
            },
        ],
        demande_ids=demande_ids,
        demande_client_ids=demande_client_ids,
    )

    assert result == [101, 102]
    assert len(captured["rows"]) == 2
    assert demande_ids == {101, 102}
    assert demande_client_ids == {11, 12}
    assert dirty_clients == [11, 12]


def test_publish_tripwire_from_db_time_uses_yellow_before_red(monkeypatch) -> None:
    published: list[dict[str, object]] = []
    monkeypatch.delenv("IMMOAPP_IMPORT_TRIPWIRE_YELLOW_SECONDS", raising=False)
    monkeypatch.delenv("IMMOAPP_IMPORT_TRIPWIRE_RED_SECONDS", raising=False)
    ensure_django()
    from server.services import import_distributed_execution

    monkeypatch.setattr(
        import_distributed_execution.runtime_pressure_tripwire,
        "publish_override",
        lambda **kwargs: published.append(dict(kwargs)),
    )

    import_distributed_execution._publish_tripwire_from_db_time(1.6)
    import_distributed_execution._publish_tripwire_from_db_time(4.2)

    assert published[0]["profile"] == "yellow"
    assert published[0]["reason"] == "yellow_sub_batch_db_time"
    assert published[1]["profile"] == "red"
    assert published[1]["reason"] == "red_sub_batch_db_time"


def _capture_batch_rows(captured: dict[str, object], rows: object) -> list[int]:
    captured["rows"] = list(rows) if isinstance(rows, list) else rows
    return [101, 102]
