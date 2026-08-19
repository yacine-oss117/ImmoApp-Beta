from __future__ import annotations

from core.data import demande_repo_read as read


class _EmptyCursor:
    def fetchall(self) -> list[object]:
        return []

    def fetchone(self) -> object | None:
        return None


class _RecordingSession:
    def __init__(self) -> None:
        self.last_query: str = ""
        self.last_params: list[object] = []

    def execute(self, query: str, params: list[object] | tuple[object, ...]) -> _EmptyCursor:
        self.last_query = query
        self.last_params = list(params)
        return _EmptyCursor()


def test_get_demandes_for_client_uses_alias_qualified_soft_delete_filter() -> None:
    session = _RecordingSession()
    _ = read.get_demandes_for_client(
        session,
        client_id=123,
        limit=50,
        offset=10,
        include_deleted=False,
    )
    normalized = " ".join(session.last_query.split())
    assert "JOIN clients" not in normalized
    assert "d.deleted_at IS NULL" in normalized
    assert "ORDER BY d.id" in normalized
    assert session.last_params == [123, 50, 10]
