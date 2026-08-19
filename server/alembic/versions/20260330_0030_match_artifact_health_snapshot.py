"""Add durable match artifact timeout counters and health samples.

Revision ID: 20260330_0030
Revises: 20260330_0029
Create Date: 2026-03-30
"""

from __future__ import annotations

from alembic import op

revision = "20260330_0030"
down_revision = "20260330_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_artifact_timeout_counters (
            id SMALLINT PRIMARY KEY,
            statement_timeout_count BIGINT NOT NULL DEFAULT 0,
            lock_timeout_count BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_match_artifact_timeout_counters_singleton CHECK (id = 1),
            CONSTRAINT chk_match_artifact_timeout_counters_statement_nonnegative
                CHECK (statement_timeout_count >= 0),
            CONSTRAINT chk_match_artifact_timeout_counters_lock_nonnegative
                CHECK (lock_timeout_count >= 0)
        )
        """)
    op.execute("""
        INSERT INTO match_artifact_timeout_counters (
            id,
            statement_timeout_count,
            lock_timeout_count,
            updated_at
        )
        VALUES (1, 0, 0, CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO NOTHING
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_artifact_health_samples (
            captured_minute TIMESTAMPTZ PRIMARY KEY,
            captured_at TIMESTAMPTZ NOT NULL,
            active_connections INTEGER NOT NULL,
            max_connections INTEGER NOT NULL,
            active_connection_ratio DOUBLE PRECISION NOT NULL,
            temp_bytes_total BIGINT NOT NULL,
            temp_bytes_delta_5m BIGINT NOT NULL,
            temp_files_total BIGINT NOT NULL,
            temp_files_delta_5m BIGINT NOT NULL,
            statement_timeout_count BIGINT NOT NULL,
            lock_timeout_count BIGINT NOT NULL,
            statement_timeout_delta_5m BIGINT NOT NULL,
            lock_timeout_delta_5m BIGINT NOT NULL,
            match_candidates_payload JSONB NOT NULL,
            match_pairs_payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_match_artifact_health_samples_active_connections_nonnegative
                CHECK (active_connections >= 0),
            CONSTRAINT chk_match_artifact_health_samples_max_connections_positive
                CHECK (max_connections > 0),
            CONSTRAINT chk_match_artifact_health_samples_connection_ratio_nonnegative
                CHECK (active_connection_ratio >= 0),
            CONSTRAINT chk_match_artifact_health_samples_temp_bytes_total_nonnegative
                CHECK (temp_bytes_total >= 0),
            CONSTRAINT chk_match_artifact_health_samples_temp_bytes_delta_nonnegative
                CHECK (temp_bytes_delta_5m >= 0),
            CONSTRAINT chk_match_artifact_health_samples_temp_files_total_nonnegative
                CHECK (temp_files_total >= 0),
            CONSTRAINT chk_match_artifact_health_samples_temp_files_delta_nonnegative
                CHECK (temp_files_delta_5m >= 0),
            CONSTRAINT chk_match_artifact_health_samples_statement_timeout_count_nonnegative
                CHECK (statement_timeout_count >= 0),
            CONSTRAINT chk_match_artifact_health_samples_lock_timeout_count_nonnegative
                CHECK (lock_timeout_count >= 0),
            CONSTRAINT chk_match_artifact_health_samples_statement_timeout_delta_nonnegative
                CHECK (statement_timeout_delta_5m >= 0),
            CONSTRAINT chk_match_artifact_health_samples_lock_timeout_delta_nonnegative
                CHECK (lock_timeout_delta_5m >= 0)
        )
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_artifact_health_samples_captured_at
        ON match_artifact_health_samples (captured_at DESC)
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_match_artifact_health_samples_captured_at")
    op.execute("DROP TABLE IF EXISTS match_artifact_health_samples")
    op.execute("DROP TABLE IF EXISTS match_artifact_timeout_counters")
