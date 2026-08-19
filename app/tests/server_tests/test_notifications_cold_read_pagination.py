from __future__ import annotations


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql: str, _params=None):
        raise AssertionError("count query should be skipped when the short page proves the total")


class _Uow:
    def session(self, **kwargs):
        return _Session()


def test_list_notifications_with_total_skips_count_on_short_offset_page(monkeypatch) -> None:
    from server.services import notifications_queries

    rows = [{"id": 30, "title": "One"}]

    monkeypatch.setattr(notifications_queries, "get_uow", lambda: _Uow())
    monkeypatch.setattr(
        notifications_queries,
        "_fetch_notification_rows",
        lambda _session, **kwargs: rows,
    )

    items, total = notifications_queries.list_notifications_with_total(
        user_id=7,
        role="manager",
        is_owner=True,
        is_superuser=False,
        limit=2,
        offset=2,
        cursor=None,
    )

    assert items == rows
    assert total == 3
