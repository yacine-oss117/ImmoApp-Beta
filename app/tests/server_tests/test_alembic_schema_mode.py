from __future__ import annotations

from contextlib import contextmanager

import pytest

import server.pg.schema as schema_mod


def test_schema_mode_rejects_non_alembic(monkeypatch):
    monkeypatch.setenv("IMMOAPP_SCHEMA_MODE", "legacy")
    with pytest.raises(RuntimeError, match="Alembic-only"):
        schema_mod.ensure_schema()


def test_schema_mode_alembic_runs_upgrade_and_post_primitives(monkeypatch):
    calls: list[str] = []

    monkeypatch.setenv("IMMOAPP_SCHEMA_MODE", "alembic")
    monkeypatch.setattr(
        schema_mod,
        "_run_alembic_upgrade_head",
        lambda *, schema: calls.append(f"upgrade:{schema}"),
    )
    monkeypatch.setattr(
        schema_mod,
        "_ensure_post_alembic_primitives",
        lambda *, schema=None: calls.append(f"post:{schema}"),
    )

    schema_mod.ensure_schema()

    assert calls == ["upgrade:public", "post:None"]


def test_non_public_schema_creates_schema_then_runs_alembic(monkeypatch):
    sql_calls: list[tuple[str, tuple[object, ...]]] = []
    calls: list[str] = []

    class _DummySession:
        def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
            sql_calls.append((sql, params))

    @contextmanager
    def _dummy_admin_transaction(*, schema: str | None = None):  # noqa: ARG001
        yield _DummySession()

    monkeypatch.setenv("IMMOAPP_SCHEMA_MODE", "alembic")
    monkeypatch.setattr(schema_mod, "admin_transaction", _dummy_admin_transaction)
    monkeypatch.setattr(
        schema_mod,
        "_run_alembic_upgrade_head",
        lambda *, schema: calls.append(f"upgrade:{schema}"),
    )
    monkeypatch.setattr(
        schema_mod,
        "_ensure_post_alembic_primitives",
        lambda *, schema=None: calls.append(f"post:{schema}"),
    )

    schema_mod.ensure_schema(schema="sim")

    assert sql_calls == [("CREATE SCHEMA IF NOT EXISTS sim", ())]
    assert calls == ["upgrade:sim"]
