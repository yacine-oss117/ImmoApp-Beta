"""Match cache privacy + key hardening + checkpoint lease table.

Revision ID: 20260221_0016
Revises: 20260220_0015
Create Date: 2026-02-21
"""

from __future__ import annotations

from alembic import op

revision = "20260221_0016"
down_revision = "20260220_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE match_counts_cache m
        SET agency_id = c.agency_id
        FROM clients c
        WHERE m.client_id = c.id
          AND (m.agency_id IS NULL OR m.agency_id <> c.agency_id)
        """)
    op.execute("""
        DELETE FROM match_counts_cache m
        WHERE m.agency_id IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM clients c WHERE c.id = m.client_id
           )
        """)

    # Cache privacy boundary: no identity columns in derived cache table.
    op.execute("ALTER TABLE match_counts_cache DROP COLUMN IF EXISTS family_name")
    op.execute("ALTER TABLE match_counts_cache DROP COLUMN IF EXISTS phone")

    op.execute("ALTER TABLE match_counts_cache ALTER COLUMN agency_id SET NOT NULL")
    op.execute("ALTER TABLE match_counts_cache ALTER COLUMN client_id SET NOT NULL")
    op.execute("ALTER TABLE match_counts_cache ALTER COLUMN count SET NOT NULL")
    op.execute("ALTER TABLE match_counts_cache ALTER COLUMN is_dirty SET NOT NULL")

    # Required for composite foreign key.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_clients_agency_id_id'
            ) THEN
                ALTER TABLE clients
                ADD CONSTRAINT uq_clients_agency_id_id UNIQUE (agency_id, id);
            END IF;
        END $$;
        """)

    op.execute("ALTER TABLE match_counts_cache DROP CONSTRAINT IF EXISTS match_counts_cache_pkey")
    op.execute("""
        ALTER TABLE match_counts_cache
        ADD CONSTRAINT match_counts_cache_pkey PRIMARY KEY (agency_id, client_id)
        """)

    # Keep client_id unique during the mixed-schema compatibility window.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_match_counts_cache_client_id "
        "ON match_counts_cache(client_id)"
    )

    op.execute(
        "ALTER TABLE match_counts_cache DROP CONSTRAINT IF EXISTS match_counts_cache_client_id_fkey"
    )
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_match_counts_cache_client_tenant'
            ) THEN
                ALTER TABLE match_counts_cache
                ADD CONSTRAINT fk_match_counts_cache_client_tenant
                FOREIGN KEY (agency_id, client_id)
                REFERENCES clients(agency_id, id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_counts_cache_agency_dirty_client "
        "ON match_counts_cache(agency_id, is_dirty, client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_counts_cache_agency_count_fresh "
        "ON match_counts_cache(agency_id, count DESC) "
        "WHERE is_dirty = 0"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_counts_cache_agency_computed_at "
        "ON match_counts_cache(agency_id, computed_at)"
    )

    # Resumable scan checkpoints for long-running keyset tasks.
    op.execute("""
        CREATE TABLE IF NOT EXISTS task_scan_checkpoints (
            task_name TEXT NOT NULL,
            agency_id BIGINT NOT NULL,
            stream_key TEXT NOT NULL,
            last_id BIGINT NOT NULL DEFAULT 0,
            rows_processed BIGINT NOT NULL DEFAULT 0,
            lease_owner TEXT,
            lease_until TIMESTAMPTZ,
            attempt INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (task_name, agency_id, stream_key)
        )
        """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_scan_checkpoints_lease "
        "ON task_scan_checkpoints(lease_until)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_scan_checkpoints_updated "
        "ON task_scan_checkpoints(updated_at)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE match_counts_cache ADD COLUMN IF NOT EXISTS family_name TEXT")
    op.execute("ALTER TABLE match_counts_cache ADD COLUMN IF NOT EXISTS phone TEXT")
    op.execute("DROP TABLE IF EXISTS task_scan_checkpoints")
