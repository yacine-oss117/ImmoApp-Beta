from __future__ import annotations

import pytest

from app.services.offline_capabilities import (
    get_offline_capability,
    require_supported_offline_action,
)


def test_supported_offline_capabilities_include_first_order_entities() -> None:
    assert get_offline_capability("client", "create").supported is True
    assert get_offline_capability("demande", "create").supported is True
    assert get_offline_capability("offer_photo", "upload").supported is True
    assert get_offline_capability("contract_article", "create").supported is True


def test_unsupported_contract_article_actions_have_explicit_reason() -> None:
    capability = get_offline_capability("contract_article", "renumber")

    assert capability.supported is False
    assert capability.reason == "Sync the contract first before working with articles."

    with pytest.raises(ValueError, match="Sync the contract first"):
        require_supported_offline_action("contract_article", "renumber")


def test_bulk_import_execute_is_explicitly_online_only() -> None:
    capability = get_offline_capability("bulk_import", "execute")

    assert capability.supported is False
    assert capability.reason == "Imports require an online connection."


def test_unknown_action_defaults_to_online_only() -> None:
    capability = get_offline_capability("mystery_entity", "explode")

    assert capability.supported is False
    assert capability.reason == "This action requires an online connection."
