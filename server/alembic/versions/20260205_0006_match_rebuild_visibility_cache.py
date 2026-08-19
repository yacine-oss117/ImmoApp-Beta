"""Match rebuild state + visibility cache columns.

Revision ID: 20260205_0006
Revises: 20260205_0005
Create Date: 2026-02-05
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260205_0006"
down_revision = "20260205_0005"
branch_labels = None
depends_on = None

AGENCY_DEFAULT_EXPR = "NULLIF(current_setting('app.current_agency_id', true), '')::bigint"
ACTOR_ID_EXPR = "NULLIF(current_setting('app.actor_id', true), '')::bigint"
ACTOR_ROLE_EXPR = "NULLIF(current_setting('app.actor_role', true), '')"
ACTOR_IS_OWNER_EXPR = "NULLIF(current_setting('app.actor_is_owner', true), '')::boolean = true"
MANAGER_OR_OWNER_EXPR = (
    f"({ACTOR_ROLE_EXPR} = ANY (ARRAY['manager','super_admin']) OR {ACTOR_IS_OWNER_EXPR})"
)

MATCH_PAIRS_PREDICATE = f"""
(
(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true)
OR (
    agency_id = {AGENCY_DEFAULT_EXPR}
    AND (
        {MANAGER_OR_OWNER_EXPR}
        OR match_pairs.demande_visibility IS NULL
        OR match_pairs.demande_visibility = 'agency'
        OR (
            match_pairs.demande_visibility = 'restricted'
            AND {ACTOR_ID_EXPR} IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM record_acl ra
                WHERE ra.table_name = 'demandes'
                  AND ra.record_id = match_pairs.demande_id
                  AND ra.user_id = {ACTOR_ID_EXPR}
            )
        )
    )
    AND (
        {MANAGER_OR_OWNER_EXPR}
        OR match_pairs.offer_visibility IS NULL
        OR match_pairs.offer_visibility = 'agency'
        OR (
            match_pairs.offer_visibility = 'restricted'
            AND {ACTOR_ID_EXPR} IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM record_acl ra
                WHERE ra.table_name = 'offers'
                  AND ra.record_id = match_pairs.offer_id
                  AND ra.user_id = {ACTOR_ID_EXPR}
            )
        )
    )
)
)
"""

MATCH_CANDIDATES_PREDICATE = f"""
(
(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true)
OR (
    agency_id = {AGENCY_DEFAULT_EXPR}
    AND (
        {MANAGER_OR_OWNER_EXPR}
        OR match_candidates.demande_visibility IS NULL
        OR match_candidates.demande_visibility = 'agency'
        OR (
            match_candidates.demande_visibility = 'restricted'
            AND {ACTOR_ID_EXPR} IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM record_acl ra
                WHERE ra.table_name = 'demandes'
                  AND ra.record_id = match_candidates.demande_id
                  AND ra.user_id = {ACTOR_ID_EXPR}
            )
        )
    )
    AND (
        {MANAGER_OR_OWNER_EXPR}
        OR match_candidates.offer_visibility IS NULL
        OR match_candidates.offer_visibility = 'agency'
        OR (
            match_candidates.offer_visibility = 'restricted'
            AND {ACTOR_ID_EXPR} IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM record_acl ra
                WHERE ra.table_name = 'offers'
                  AND ra.record_id = match_candidates.offer_id
                  AND ra.user_id = {ACTOR_ID_EXPR}
            )
        )
    )
)
)
"""

MATCH_REBUILD_PREDICATE = (
    f"(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
    f"OR (agency_id = {AGENCY_DEFAULT_EXPR})"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_rebuild_state (
            scope TEXT NOT NULL,
            scope_id BIGINT NOT NULL,
            agency_id BIGINT,
            pending BOOLEAN NOT NULL DEFAULT FALSE,
            generation BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope, scope_id, agency_id)
        )
        """)
    op.execute("DROP INDEX IF EXISTS idx_match_rebuild_state_agency")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_rebuild_state_agency_id "
        "ON match_rebuild_state(agency_id)"
    )
    op.execute(
        f"ALTER TABLE match_rebuild_state ALTER COLUMN agency_id SET DEFAULT {AGENCY_DEFAULT_EXPR}"
    )
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM match_rebuild_state WHERE agency_id IS NULL) THEN
                ALTER TABLE match_rebuild_state ALTER COLUMN agency_id SET NOT NULL;
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'accounts_agency') THEN
                ALTER TABLE match_rebuild_state
                ADD CONSTRAINT fk_match_rebuild_state_agency
                FOREIGN KEY (agency_id) REFERENCES accounts_agency(id);
            END IF;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("ALTER TABLE match_rebuild_state ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE match_rebuild_state FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS policy_match_rebuild_state_isolation ON match_rebuild_state")
    op.execute(f"""
        CREATE POLICY policy_match_rebuild_state_isolation ON match_rebuild_state
        USING ({MATCH_REBUILD_PREDICATE})
        WITH CHECK ({MATCH_REBUILD_PREDICATE})
        """)

    op.execute("ALTER TABLE match_candidates ADD COLUMN IF NOT EXISTS demande_visibility TEXT")
    op.execute("ALTER TABLE match_candidates ADD COLUMN IF NOT EXISTS offer_visibility TEXT")
    op.execute("ALTER TABLE match_candidates ADD COLUMN IF NOT EXISTS demande_owner_user_id BIGINT")
    op.execute("ALTER TABLE match_candidates ADD COLUMN IF NOT EXISTS offer_owner_user_id BIGINT")
    op.execute("ALTER TABLE match_pairs ADD COLUMN IF NOT EXISTS demande_visibility TEXT")
    op.execute("ALTER TABLE match_pairs ADD COLUMN IF NOT EXISTS offer_visibility TEXT")
    op.execute("ALTER TABLE match_pairs ADD COLUMN IF NOT EXISTS demande_owner_user_id BIGINT")
    op.execute("ALTER TABLE match_pairs ADD COLUMN IF NOT EXISTS offer_owner_user_id BIGINT")

    op.execute("""
        UPDATE match_candidates mc
        SET demande_visibility = d.visibility,
            offer_visibility = o.visibility,
            demande_owner_user_id = d.owner_user_id,
            offer_owner_user_id = o.owner_user_id
        FROM demandes d, offers o
        WHERE mc.demande_id = d.id
          AND o.id = mc.offer_id
          AND (mc.demande_visibility IS NULL OR mc.offer_visibility IS NULL)
    """)
    op.execute("""
        UPDATE match_pairs mp
        SET demande_visibility = d.visibility,
            offer_visibility = o.visibility,
            demande_owner_user_id = d.owner_user_id,
            offer_owner_user_id = o.owner_user_id
        FROM demandes d, offers o
        WHERE mp.demande_id = d.id
          AND o.id = mp.offer_id
          AND (mp.demande_visibility IS NULL OR mp.offer_visibility IS NULL)
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION sync_match_visibility_from_demande()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE match_candidates
            SET demande_visibility = NEW.visibility,
                demande_owner_user_id = NEW.owner_user_id
            WHERE demande_id = NEW.id;
            UPDATE match_pairs
            SET demande_visibility = NEW.visibility,
                demande_owner_user_id = NEW.owner_user_id
            WHERE demande_id = NEW.id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_match_visibility_from_offer()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE match_candidates
            SET offer_visibility = NEW.visibility,
                offer_owner_user_id = NEW.owner_user_id
            WHERE offer_id = NEW.id;
            UPDATE match_pairs
            SET offer_visibility = NEW.visibility,
                offer_owner_user_id = NEW.owner_user_id
            WHERE offer_id = NEW.id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)
    op.execute("""
        DO $$
        BEGIN
            CREATE TRIGGER trg_sync_match_visibility_demande
            AFTER UPDATE OF visibility, owner_user_id ON demandes
            FOR EACH ROW EXECUTE FUNCTION sync_match_visibility_from_demande();
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            CREATE TRIGGER trg_sync_match_visibility_offer
            AFTER UPDATE OF visibility, owner_user_id ON offers
            FOR EACH ROW EXECUTE FUNCTION sync_match_visibility_from_offer();
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)

    op.execute("DROP POLICY IF EXISTS policy_match_pairs_isolation ON match_pairs")
    op.execute(f"""
        CREATE POLICY policy_match_pairs_isolation ON match_pairs
        USING ({MATCH_PAIRS_PREDICATE})
        WITH CHECK ({MATCH_PAIRS_PREDICATE})
        """)
    op.execute("DROP POLICY IF EXISTS policy_match_candidates_isolation ON match_candidates")
    op.execute(f"""
        CREATE POLICY policy_match_candidates_isolation ON match_candidates
        USING ({MATCH_CANDIDATES_PREDICATE})
        WITH CHECK ({MATCH_CANDIDATES_PREDICATE})
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS policy_match_pairs_isolation ON match_pairs")
    op.execute("DROP POLICY IF EXISTS policy_match_candidates_isolation ON match_candidates")
    op.execute("DROP POLICY IF EXISTS policy_match_rebuild_state_isolation ON match_rebuild_state")
    op.execute("DROP TRIGGER IF EXISTS trg_sync_match_visibility_demande ON demandes")
    op.execute("DROP TRIGGER IF EXISTS trg_sync_match_visibility_offer ON offers")
    op.execute("DROP FUNCTION IF EXISTS sync_match_visibility_from_demande()")
    op.execute("DROP FUNCTION IF EXISTS sync_match_visibility_from_offer()")
    op.execute("ALTER TABLE match_pairs DROP COLUMN IF EXISTS demande_visibility")
    op.execute("ALTER TABLE match_pairs DROP COLUMN IF EXISTS offer_visibility")
    op.execute("ALTER TABLE match_pairs DROP COLUMN IF EXISTS demande_owner_user_id")
    op.execute("ALTER TABLE match_pairs DROP COLUMN IF EXISTS offer_owner_user_id")
    op.execute("ALTER TABLE match_candidates DROP COLUMN IF EXISTS demande_visibility")
    op.execute("ALTER TABLE match_candidates DROP COLUMN IF EXISTS offer_visibility")
    op.execute("ALTER TABLE match_candidates DROP COLUMN IF EXISTS demande_owner_user_id")
    op.execute("ALTER TABLE match_candidates DROP COLUMN IF EXISTS offer_owner_user_id")
    op.execute("DROP INDEX IF EXISTS idx_match_rebuild_state_agency_id")
    op.execute("ALTER TABLE match_rebuild_state DROP COLUMN IF EXISTS pending")
