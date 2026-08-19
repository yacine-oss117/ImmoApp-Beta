from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_seed_initial_creates_local_owner_user() -> None:
    text = _read("server/services/local_dev_seed.py")
    assert 'username="owner"' in text
    assert '"email": "owner@example.com"' in text or 'email="owner@example.com"' in text
    assert '"role": User.ROLE_MANAGER' in text or "role=User.ROLE_MANAGER" in text
    assert '"agency": agency' in text or "agency=agency" in text
    assert '"is_owner": True' in text or "is_owner=True" in text
    assert '"can_import": True' in text or "can_import=True" in text


def test_local_seed_hashes_password_before_first_user_save() -> None:
    text = _read("server/services/local_dev_seed.py")
    assert "User.objects.get_or_create" not in text
    assert "user.set_password(password)" in text
    assert "user.save(validate=False)" in text


def test_stack_bootstrap_runs_local_seed_after_db_prepare() -> None:
    text = _read("scripts/stack.ps1")
    assert '"immoapp_db_prepare", "--seed-local-dev"' in text


def test_db_prepare_command_supports_local_seed_flag() -> None:
    text = _read("server/api/management/commands/immoapp_db_prepare.py")
    assert "--seed-local-dev" in text
    assert "seed_local_dev_identities" in text
