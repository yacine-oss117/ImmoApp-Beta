from __future__ import annotations

import pytest

import core.encryption as encryption_module
from core.models_client import Client
from core.models_crm import Contract, Visit
from core.models_demande import Demande
from core.models_listing import Listing
from core.models_offer import Offer


def _reset_encryption_singleton() -> None:
    encryption_module._instance = None


def _clear_ale_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALE_MASTER_KEY", raising=False)
    monkeypatch.delenv("ALE_MASTER_KEYS", raising=False)
    monkeypatch.delenv("ALE_MASTER_KEY_V1", raising=False)
    monkeypatch.delenv("ALE_KDF_SALT", raising=False)
    monkeypatch.delenv("ALE_KEY_VERSION", raising=False)
    _reset_encryption_singleton()


def test_client_from_row_no_ale_key_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ale_env(monkeypatch)
    row = {
        "id": 1,
        "family_name": "Alice",
        "phone": "0555",
        "remarks": "note",
        "family_name_enc": "v1:enc",
        "phone_enc": "v1:enc",
        "remarks_enc": "v1:enc",
    }
    client = Client.from_row(row)
    assert client.id == 1
    assert client.family_name == "Alice"
    assert client.phone == "0555"
    assert client.remarks == "note"


def test_listing_offer_demande_from_row_no_ale_key_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_ale_env(monkeypatch)

    listing = Listing.from_row(
        {
            "id": 2,
            "family_name": "Owner",
            "phone": "0666",
            "remarks": "r",
            "family_name_enc": "v1:enc",
            "phone_enc": "v1:enc",
            "remarks_enc": "v1:enc",
        }
    )
    offer = Offer.from_row(
        {
            "id": 3,
            "listing_id": 2,
            "type": "apartment",
            "action": "rent",
            "location": "Hydra",
            "remarks": "offer-note",
            "remarks_enc": "v1:enc",
            "location_enc": "v1:enc",
        }
    )
    demande = Demande.from_row(
        {
            "id": 4,
            "client_id": 1,
            "type": "apartment",
            "action": "rent",
            "locations": "Hydra",
            "remarks": "demande-note",
            "remarks_enc": "v1:enc",
            "locations_enc": "v1:enc",
        }
    )

    assert listing.id == 2
    assert offer.id == 3
    assert demande.id == 4
    assert offer.location == "Hydra"
    assert demande.locations == "Hydra"


def test_crm_models_from_row_no_ale_key_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ale_env(monkeypatch)

    visit = Visit.from_row(
        {
            "id": 5,
            "client_id": 1,
            "listing_id": 2,
            "scheduled_date": "2026-02-13",
            "scheduled_time": "10:00",
            "notes": "visit-note",
            "notes_enc": "v1:enc",
        }
    )
    contract = Contract.from_row(
        {
            "id": 6,
            "client_id": 1,
            "listing_id": 2,
            "contract_type": "rent",
            "start_date": "2026-02-14",
            "end_date": "2027-02-14",
            "amount": 1000.0,
            "deposit": 500.0,
            "terms": "terms",
            "notes": "contract-note",
            "amount_enc": "v1:enc",
            "deposit_enc": "v1:enc",
            "terms_enc": "v1:enc",
            "notes_enc": "v1:enc",
        }
    )

    assert visit.id == 5
    assert visit.notes == "visit-note"
    assert contract.id == 6
    assert contract.notes == "contract-note"
