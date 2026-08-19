"""Denormalize match_counts_cache visibility + update RLS policy.

Revision ID: 20260206_0008
Revises: 20260205_0007
Create Date: 2026-02-06
"""

from __future__ import annotations

from alembic import op

revision = "20260206_0008"
down_revision = "20260205_0007"
branch_labels = None
depends_on = None


_POLICY = """
(
  (NULLIF(current_setting('app.is_superuser', true), '')::boolean = true)
  OR (
    agency_id = (NULLIF(current_setting('app.current_agency_id', true), '')::bigint)
    AND (
      (NULLIF(current_setting('app.actor_role', true), '') = ANY (ARRAY['manager','super_admin']))
      OR (NULLIF(current_setting('app.actor_is_owner', true), '')::boolean = true)
      OR match_counts_cache.visibility IS NULL
      OR match_counts_cache.visibility = 'agency'
      OR (
        match_counts_cache.visibility = 'restricted'
        AND (NULLIF(current_setting('app.actor_id', true), '')::bigint IS NOT NULL)
        AND EXISTS (
          SELECT 1 FROM record_acl ra
          WHERE ra.table_name = 'clients'
            AND ra.record_id = match_counts_cache.client_id
            AND ra.user_id = (NULLIF(current_setting('app.actor_id', true), '')::bigint)
        )
      )
    )
  )
)
"""


def upgrade() -> None:
    op.execute("ALTER TABLE match_counts_cache ADD COLUMN IF NOT EXISTS visibility TEXT")
    op.execute("ALTER TABLE match_counts_cache ADD COLUMN IF NOT EXISTS owner_user_id BIGINT")
    op.execute("""
        UPDATE match_counts_cache m
        SET visibility = c.visibility,
            owner_user_id = c.owner_user_id
        FROM clients c
        WHERE m.client_id = c.id
          AND (m.visibility IS NULL OR m.owner_user_id IS NULL)
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_match_cache_from_client()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.deleted_at IS NOT NULL OR NEW.status <> 'active' THEN
                DELETE FROM match_counts_cache WHERE client_id = NEW.id;
                RETURN NEW;
            END IF;
            UPDATE match_counts_cache
            SET visibility = NEW.visibility,
                owner_user_id = NEW.owner_user_id
            WHERE client_id = NEW.id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)
    op.execute("""
        DO $$
        BEGIN
            CREATE TRIGGER trg_sync_match_cache_client
            AFTER UPDATE OF visibility, owner_user_id, status, deleted_at ON clients
            FOR EACH ROW EXECUTE FUNCTION sync_match_cache_from_client();
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("DROP POLICY IF EXISTS policy_match_counts_cache_isolation ON match_counts_cache")
    op.execute(f"""
        CREATE POLICY policy_match_counts_cache_isolation ON match_counts_cache
        USING ({_POLICY})
        WITH CHECK ({_POLICY})
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS policy_match_counts_cache_isolation ON match_counts_cache")
    op.execute("""
        CREATE POLICY policy_match_counts_cache_isolation ON match_counts_cache
        USING (true)
        WITH CHECK (true)
        """)
    op.execute("DROP TRIGGER IF EXISTS trg_sync_match_cache_client ON clients")
    op.execute("DROP FUNCTION IF EXISTS sync_match_cache_from_client()")
    op.execute("ALTER TABLE match_counts_cache DROP COLUMN IF EXISTS owner_user_id")
    op.execute("ALTER TABLE match_counts_cache DROP COLUMN IF EXISTS visibility")
