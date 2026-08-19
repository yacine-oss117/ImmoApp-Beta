"""Add durable API idempotency record store."""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260221_0017"
down_revision = "20260221_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_idempotency_records (
            id BIGSERIAL PRIMARY KEY,
            agency_id BIGINT NOT NULL,
            normalized_route TEXT NOT NULL,
            method TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            canonical_body_hash TEXT NOT NULL,
            normalized_query_hash TEXT NOT NULL,
            semantic_headers_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            lease_owner TEXT,
            lease_until TIMESTAMPTZ,
            status_code INTEGER,
            response_content_type TEXT,
            response_headers_json JSONB,
            response_body_json JSONB,
            response_body_hash TEXT,
            response_size_bytes INTEGER,
            record_hmac TEXT,
            signature_key_id TEXT,
            hmac_payload_version TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_api_idempotency_scope UNIQUE (
                agency_id,
                normalized_route,
                method,
                idempotency_key
            ),
            CONSTRAINT chk_api_idempotency_state CHECK (
                state IN ('in_progress', 'completed', 'failed_transient')
            ),
            CONSTRAINT chk_api_idempotency_response_size CHECK (
                response_size_bytes IS NULL OR response_size_bytes <= 262144
            )
        )
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_idempotency_expires_at
        ON api_idempotency_records (expires_at)
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_idempotency_in_progress
        ON api_idempotency_records (agency_id, normalized_route, method, idempotency_key)
        WHERE state = 'in_progress'
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_idempotency_records")
