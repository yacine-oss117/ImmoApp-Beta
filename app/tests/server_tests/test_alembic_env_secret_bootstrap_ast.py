from __future__ import annotations

from pathlib import Path


def test_alembic_env_bootstraps_db_credentials_from_secrets() -> None:
    text = Path("server/alembic/env.py").read_text(encoding="utf-8")
    assert "def _load_db_credentials_from_secrets" in text
    assert "IMMOAPP_SECRETS_ALLOWLIST" in text
    assert "POSTGRES_" in text
    assert "load_secrets()" in text


def test_alembic_env_has_no_hardcoded_postgres_credential_defaults() -> None:
    text = Path("server/alembic/env.py").read_text(encoding="utf-8")
    banned_snippets = (
        'POSTGRES_USER", "postgres"',
        'POSTGRES_PASSWORD", "postgres"',
        'POSTGRES_DB", "postgres"',
    )
    for snippet in banned_snippets:
        assert snippet not in text, f"Alembic env must not hardcode default credential: {snippet}"
