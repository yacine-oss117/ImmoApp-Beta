"""Add durable tenant-scoped response-cache generations.

Revision ID: 20260330_0028
Revises: 20260313_0027
Create Date: 2026-03-30
"""

from __future__ import annotations

from alembic import op

revision = "20260330_0028"
down_revision = "20260313_0027"
branch_labels = None
depends_on = None

AGENCY_DEFAULT_EXPR = "NULLIF(current_setting('app.current_agency_id', true), '')::bigint"
SURFACE_GENERATION_PREDICATE = (
    f"(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
    f"OR (agency_id = {AGENCY_DEFAULT_EXPR})"
)


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS surface_cache_generation (
            surface TEXT NOT NULL,
            agency_id BIGINT NOT NULL DEFAULT {AGENCY_DEFAULT_EXPR},
            generation BIGINT NOT NULL DEFAULT 1,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT pk_surface_cache_generation PRIMARY KEY (surface, agency_id),
            CONSTRAINT chk_surface_cache_generation_surface
                CHECK (surface IN ('clients_surface', 'listings_surface')),
            CONSTRAINT chk_surface_cache_generation_generation
                CHECK (generation >= 1)
        )
        """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_surface_cache_generation_agency_id "
        "ON surface_cache_generation(agency_id)"
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'accounts_agency') THEN
                ALTER TABLE surface_cache_generation
                ADD CONSTRAINT fk_surface_cache_generation_agency
                FOREIGN KEY (agency_id) REFERENCES accounts_agency(id) ON DELETE CASCADE;
            END IF;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("ALTER TABLE surface_cache_generation ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE surface_cache_generation FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS policy_surface_cache_generation_isolation "
        "ON surface_cache_generation"
    )
    op.execute(f"""
        CREATE POLICY policy_surface_cache_generation_isolation
        ON surface_cache_generation
        USING ({SURFACE_GENERATION_PREDICATE})
        WITH CHECK ({SURFACE_GENERATION_PREDICATE})
        """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS policy_surface_cache_generation_isolation "
        "ON surface_cache_generation"
    )
    op.execute("DROP TABLE IF EXISTS surface_cache_generation")
