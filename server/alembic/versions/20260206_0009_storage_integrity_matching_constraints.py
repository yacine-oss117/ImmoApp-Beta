"""Enforce storage ownership integrity + matching constraints.

Revision ID: 20260206_0009
Revises: 20260206_0008
Create Date: 2026-02-06
"""

from __future__ import annotations

from alembic import op

revision = "20260206_0009"
down_revision = "20260206_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE property_types "
        "ADD COLUMN IF NOT EXISTS requires_floor BOOLEAN NOT NULL DEFAULT FALSE"
    )

    op.execute("""
        DO $$
        DECLARE
            user_count INTEGER;
            fallback_user_id BIGINT;
            fallback_role TEXT;
        BEGIN
            IF to_regclass('public.storage_objects') IS NULL THEN
                RETURN;
            END IF;
            IF EXISTS (SELECT 1 FROM storage_objects WHERE user_id IS NULL OR role IS NULL LIMIT 1) THEN
                IF to_regclass('public.accounts_user') IS NULL THEN
                    RAISE EXCEPTION 'storage_objects.user_id/role must be backfilled before enforcing NOT NULL';
                END IF;
                SELECT COUNT(*) INTO user_count FROM accounts_user;
                IF user_count = 1 THEN
                    SELECT id, role INTO fallback_user_id, fallback_role FROM accounts_user ORDER BY id LIMIT 1;
                    UPDATE storage_objects
                    SET user_id = COALESCE(user_id, fallback_user_id),
                        role = COALESCE(role, fallback_role)
                    WHERE user_id IS NULL OR role IS NULL;
                ELSE
                    RAISE EXCEPTION 'storage_objects.user_id/role must be backfilled before enforcing NOT NULL';
                END IF;
            END IF;
            ALTER TABLE storage_objects ALTER COLUMN user_id SET NOT NULL;
            ALTER TABLE storage_objects ALTER COLUMN role SET NOT NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE storage_objects
            ADD CONSTRAINT chk_storage_objects_role
            CHECK (role IN ('super_admin', 'manager', 'agent'));
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE storage_events
            ADD CONSTRAINT chk_storage_events_role
            CHECK (role IS NULL OR role IN ('super_admin', 'manager', 'agent'));
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.accounts_user') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE storage_objects
            ADD CONSTRAINT fk_storage_objects_user
            FOREIGN KEY (user_id) REFERENCES accounts_user(id) ON DELETE RESTRICT;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.accounts_user') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE storage_events
            ADD CONSTRAINT fk_storage_events_user
            FOREIGN KEY (user_id) REFERENCES accounts_user(id) ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.accounts_user') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE record_acl
            ADD CONSTRAINT fk_record_acl_user
            FOREIGN KEY (user_id) REFERENCES accounts_user(id) ON DELETE RESTRICT;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)

    # Purge legacy incomplete rows before enforcing strict NOT NULL constraints.
    op.execute("""
        DELETE FROM demandes
        WHERE action_id IS NULL
           OR budget_min IS NULL
           OR budget_max IS NULL
           OR surface_min IS NULL
           OR surface_max IS NULL
           OR beds_min IS NULL
        """)
    op.execute("""
        DELETE FROM offers
        WHERE action_id IS NULL
           OR type_id IS NULL
           OR wilaya_id IS NULL
           OR location IS NULL
           OR beds IS NULL
           OR surface IS NULL
           OR budget IS NULL
           OR floor IS NULL
           OR elevator IS NULL
           OR accessibility_supported IS NULL
        """)

    op.execute(
        "ALTER TABLE demandes ALTER COLUMN budget_range "
        "SET DEFAULT numrange(0::numeric, NULL, '[]')"
    )
    op.execute(
        "ALTER TABLE demandes ALTER COLUMN surface_range "
        "SET DEFAULT numrange(0::numeric, NULL, '[]')"
    )
    op.execute(
        "ALTER TABLE demandes ALTER COLUMN beds_range " "SET DEFAULT int4range(0, NULL, '[]')"
    )
    op.execute("ALTER TABLE demandes ALTER COLUMN budget_range SET NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN surface_range SET NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN beds_range SET NOT NULL")

    op.execute("ALTER TABLE demandes ALTER COLUMN action_id SET NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN budget_min SET NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN budget_max SET NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN surface_min SET NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN surface_max SET NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN beds_min SET NOT NULL")

    op.execute("ALTER TABLE offers ALTER COLUMN action_id SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN type_id SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN wilaya_id SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN location SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN beds SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN surface SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN budget SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN floor SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN elevator SET NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN accessibility_supported SET NOT NULL")

    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE demandes
            ADD CONSTRAINT chk_demandes_budget_bounds
            CHECK (budget_min <= budget_max);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE demandes
            ADD CONSTRAINT chk_demandes_surface_bounds
            CHECK (surface_min <= surface_max);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE demandes
            ADD CONSTRAINT chk_demandes_beds_min
            CHECK (beds_min >= 0);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE offers
            ADD CONSTRAINT chk_offers_budget_nonnegative
            CHECK (budget >= 0);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE offers
            ADD CONSTRAINT chk_offers_surface_nonnegative
            CHECK (surface >= 0);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)

    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_demande_floor_requirement()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.type_id IS NOT NULL THEN
                IF EXISTS (
                    SELECT 1 FROM property_types
                    WHERE id = NEW.type_id AND requires_floor = true
                ) THEN
                    IF NEW.floor_min IS NULL OR NEW.floor_max IS NULL THEN
                        RAISE EXCEPTION 'floor_min/floor_max required for apartment-type demandes';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            DROP TRIGGER IF EXISTS trg_demande_floor_required ON demandes;
            CREATE TRIGGER trg_demande_floor_required
            BEFORE INSERT OR UPDATE ON demandes
            FOR EACH ROW EXECUTE FUNCTION enforce_demande_floor_requirement();
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_demande_floor_required ON demandes")
    op.execute("DROP FUNCTION IF EXISTS enforce_demande_floor_requirement()")
    op.execute("ALTER TABLE demandes ALTER COLUMN budget_range DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN surface_range DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN beds_range DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN budget_range DROP DEFAULT")
    op.execute("ALTER TABLE demandes ALTER COLUMN surface_range DROP DEFAULT")
    op.execute("ALTER TABLE demandes ALTER COLUMN beds_range DROP DEFAULT")
    op.execute("ALTER TABLE demandes ALTER COLUMN action_id DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN budget_min DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN budget_max DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN surface_min DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN surface_max DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN beds_min DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN action_id DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN type_id DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN wilaya_id DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN location DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN beds DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN surface DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN budget DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN floor DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN elevator DROP NOT NULL")
    op.execute("ALTER TABLE offers ALTER COLUMN accessibility_supported DROP NOT NULL")
    op.execute("ALTER TABLE storage_objects ALTER COLUMN user_id DROP NOT NULL")
    op.execute("ALTER TABLE storage_objects ALTER COLUMN role DROP NOT NULL")
    op.execute("ALTER TABLE storage_objects DROP CONSTRAINT IF EXISTS chk_storage_objects_role")
    op.execute("ALTER TABLE storage_events DROP CONSTRAINT IF EXISTS chk_storage_events_role")
    op.execute("ALTER TABLE storage_objects DROP CONSTRAINT IF EXISTS fk_storage_objects_user")
    op.execute("ALTER TABLE storage_events DROP CONSTRAINT IF EXISTS fk_storage_events_user")
    op.execute("ALTER TABLE record_acl DROP CONSTRAINT IF EXISTS fk_record_acl_user")
    op.execute("ALTER TABLE property_types DROP COLUMN IF EXISTS requires_floor")
