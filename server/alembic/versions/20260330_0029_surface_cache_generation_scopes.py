"""Refine surface cache generations to explicit scoped identities.

Revision ID: 20260330_0029
Revises: 20260330_0028
Create Date: 2026-03-30
"""

from __future__ import annotations

from alembic import op

revision = "20260330_0029"
down_revision = "20260330_0028"
branch_labels = None
depends_on = None

AGENCY_DEFAULT_EXPR = "NULLIF(current_setting('app.current_agency_id', true), '')::bigint"
SURFACE_GENERATION_PREDICATE = (
    f"(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
    f"OR (agency_id IS NOT NULL AND agency_id = {AGENCY_DEFAULT_EXPR})"
)
SURFACES = (
    "clients_surface",
    "listings_surface",
    "users_surface",
    "invites_agency_surface",
    "invites_actor_surface",
    "notifications_agency_surface",
    "notifications_role_surface",
    "notifications_owner_surface",
    "notifications_actor_surface",
    "notifications_global_surface",
)
SURFACE_CHECK_SQL = ", ".join(f"'{surface}'" for surface in SURFACES)


def upgrade() -> None:
    op.execute("ALTER TABLE surface_cache_generation ADD COLUMN IF NOT EXISTS scope_key TEXT")
    op.execute("""
        UPDATE surface_cache_generation
        SET scope_key = 'agency:' || agency_id::text
        WHERE scope_key IS NULL OR btrim(scope_key) = ''
        """)
    op.execute("ALTER TABLE surface_cache_generation ALTER COLUMN scope_key SET NOT NULL")
    op.execute(
        "ALTER TABLE surface_cache_generation DROP CONSTRAINT IF EXISTS pk_surface_cache_generation"
    )
    op.execute("ALTER TABLE surface_cache_generation ALTER COLUMN agency_id DROP DEFAULT")
    op.execute("ALTER TABLE surface_cache_generation ALTER COLUMN agency_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE surface_cache_generation "
        "ADD CONSTRAINT pk_surface_cache_generation PRIMARY KEY (surface, scope_key)"
    )
    op.execute("DROP INDEX IF EXISTS idx_surface_cache_generation_agency_id")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_surface_cache_generation_agency_id "
        "ON surface_cache_generation(agency_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_surface_cache_generation_scope_key "
        "ON surface_cache_generation(scope_key)"
    )
    op.execute(
        "ALTER TABLE surface_cache_generation "
        "DROP CONSTRAINT IF EXISTS chk_surface_cache_generation_surface"
    )
    op.execute(f"""
        ALTER TABLE surface_cache_generation
        ADD CONSTRAINT chk_surface_cache_generation_surface
        CHECK (surface IN ({SURFACE_CHECK_SQL}))
        """)
    op.execute(
        "ALTER TABLE surface_cache_generation "
        "DROP CONSTRAINT IF EXISTS chk_surface_cache_generation_scope_identity"
    )
    op.execute("""
        ALTER TABLE surface_cache_generation
        ADD CONSTRAINT chk_surface_cache_generation_scope_identity
        CHECK (
            (scope_key = 'global' AND agency_id IS NULL)
            OR (
                scope_key <> 'global'
                AND agency_id IS NOT NULL
                AND (
                    scope_key LIKE 'agency:%'
                    OR scope_key LIKE 'actor:%'
                    OR scope_key LIKE 'role:%:%'
                    OR scope_key LIKE 'owner:%'
                )
            )
        )
        """)
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
        "DELETE FROM surface_cache_generation "
        "WHERE scope_key = 'global' OR scope_key NOT LIKE 'agency:%'"
    )
    op.execute("""
        UPDATE surface_cache_generation
        SET agency_id = NULLIF(split_part(scope_key, ':', 2), '')::bigint
        WHERE scope_key LIKE 'agency:%'
        """)
    op.execute(
        "DROP POLICY IF EXISTS policy_surface_cache_generation_isolation "
        "ON surface_cache_generation"
    )
    op.execute(
        "ALTER TABLE surface_cache_generation "
        "DROP CONSTRAINT IF EXISTS chk_surface_cache_generation_scope_identity"
    )
    op.execute(
        "ALTER TABLE surface_cache_generation "
        "DROP CONSTRAINT IF EXISTS chk_surface_cache_generation_surface"
    )
    op.execute("""
        ALTER TABLE surface_cache_generation
        ADD CONSTRAINT chk_surface_cache_generation_surface
        CHECK (surface IN ('clients_surface', 'listings_surface'))
        """)
    op.execute(
        "ALTER TABLE surface_cache_generation DROP CONSTRAINT IF EXISTS pk_surface_cache_generation"
    )
    op.execute(
        "ALTER TABLE surface_cache_generation "
        "ADD CONSTRAINT pk_surface_cache_generation PRIMARY KEY (surface, agency_id)"
    )
    op.execute("DROP INDEX IF EXISTS idx_surface_cache_generation_scope_key")
    op.execute(
        "ALTER TABLE surface_cache_generation ALTER COLUMN agency_id "
        f"SET DEFAULT {AGENCY_DEFAULT_EXPR}"
    )
    op.execute("ALTER TABLE surface_cache_generation ALTER COLUMN agency_id SET NOT NULL")
    op.execute("ALTER TABLE surface_cache_generation DROP COLUMN IF EXISTS scope_key")
    op.execute(f"""
        CREATE POLICY policy_surface_cache_generation_isolation
        ON surface_cache_generation
        USING ({SURFACE_GENERATION_PREDICATE})
        WITH CHECK ({SURFACE_GENERATION_PREDICATE})
        """)
