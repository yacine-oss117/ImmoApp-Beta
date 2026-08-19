from __future__ import annotations

import pytest

from app.services import crm_articles
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_op_log import list_operations
from app.services.offline_projection import get_projection_record


def _scope(suffix: str = "articles") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_create_article_under_temp_contract_returns_temp_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.offline_entity_mutations as mutations

    scope = _scope("create-temp-contract")
    monkeypatch.setenv("IMMOAPP_OFFLINE_CREATES_ENABLED", "1")
    monkeypatch.setattr(mutations, "require_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        mutations.api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    article_id = crm_articles.create_article(-1, 1, "Title", "Content")

    assert article_id < 0
    ops = list_operations(scope=scope)
    assert len(ops) == 1
    assert ops[0].entity_type == "contract_article"
    assert ops[0].status == "blocked"
    projection = get_projection_record("contract_article", article_id, scope=scope)
    assert projection is not None
    assert int(projection.data["contract_id"]) == -1
    assert projection.sync_status == "blocked"


def test_get_articles_for_temp_contract_returns_local_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.offline_entity_mutations as mutations

    scope = _scope("list-temp-contract")
    monkeypatch.setenv("IMMOAPP_OFFLINE_CREATES_ENABLED", "1")
    monkeypatch.setattr(mutations, "require_active_account_scope", lambda: scope)
    monkeypatch.setattr(crm_articles, "get_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        mutations.api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    article_id = crm_articles.create_article(-2, 2, "Offline Clause", "Body")
    items = crm_articles.get_articles_for_contract(-2)

    assert len(items) == 1
    assert int(items[0]["id"]) == article_id
    assert int(items[0]["contract_id"]) == -2
    assert items[0]["sync_status"] == "blocked"
    assert items[0]["is_local_only"] is True


def test_update_article_merges_into_pending_temp_create(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.offline_entity_mutations as mutations

    scope = _scope("update-temp-article")
    monkeypatch.setenv("IMMOAPP_OFFLINE_CREATES_ENABLED", "1")
    monkeypatch.setattr(mutations, "require_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        mutations.api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    article_id = crm_articles.create_article(-3, 3, "Draft", "One")

    assert crm_articles.update_article(article_id, "Draft 2", "Two") is True
    ops = list_operations(scope=scope)
    assert len(ops) == 1
    assert ops[0].op_type == "create"
    assert ops[0].payload["body"]["title"] == "Draft 2"
    assert ops[0].payload["body"]["content"] == "Two"


def test_delete_article_cancels_pending_temp_create(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.offline_entity_mutations as mutations

    scope = _scope("delete-temp-article")
    monkeypatch.setenv("IMMOAPP_OFFLINE_CREATES_ENABLED", "1")
    monkeypatch.setattr(mutations, "require_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        mutations.api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    article_id = crm_articles.create_article(-4, 4, "Draft", "One")

    assert crm_articles.delete_article(article_id) is True
    assert list_operations(scope=scope) == []
    assert get_projection_record("contract_article", article_id, scope=scope) is None


def test_contract_article_actions_reject_temp_contract_id() -> None:
    with pytest.raises(ValueError, match="Sync the contract first"):
        crm_articles.renumber_articles(-1)
    with pytest.raises(ValueError, match="Sync the contract first"):
        crm_articles.copy_standard_clauses(-1, {"kind": "sale"})
