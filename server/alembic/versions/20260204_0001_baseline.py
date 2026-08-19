"""Baseline runtime schema bootstrap (Alembic-owned).

Revision ID: 20260204_0001
Revises:
Create Date: 2026-02-04
"""

from __future__ import annotations

from alembic import op

revision = "20260204_0001"
down_revision = None
branch_labels = None
depends_on = None

AGENCY_DEFAULT_EXPR = "NULLIF(current_setting('app.current_agency_id', true), '')::bigint"
ACTOR_ID_EXPR = "NULLIF(current_setting('app.actor_id', true), '')::bigint"
ACTOR_ROLE_EXPR = "NULLIF(current_setting('app.actor_role', true), '')"
ACTOR_IS_OWNER_EXPR = "NULLIF(current_setting('app.actor_is_owner', true), '')::boolean = true"
MANAGER_OR_OWNER_EXPR = (
    f"({ACTOR_ROLE_EXPR} = ANY (ARRAY['manager','super_admin']) OR {ACTOR_IS_OWNER_EXPR})"
)
RLS_PREDICATE = (
    "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
    f"OR (agency_id = {AGENCY_DEFAULT_EXPR})"
)

TENANT_TABLES = [
    "clients",
    "listings",
    "visits",
    "contracts",
    "demandes",
    "offers",
    "demande_locations",
    "offer_locations",
    "match_counts_cache",
    "match_candidates",
    "match_pairs",
    "match_rebuild_state",
    "custom_locations",
    "contract_articles",
    "wa_templates",
    "audit_logs",
    "task_failures",
    "notifications",
    "notification_reads",
    "auth_security_events",
    "storage_objects",
    "offer_photos",
    "record_acl",
    "storage_usage",
    "storage_events",
    "agency_settings",
]

TENANT_TABLES_NOT_NULL = {
    "clients",
    "listings",
    "visits",
    "contracts",
    "demandes",
    "offers",
    "demande_locations",
    "offer_locations",
    "match_counts_cache",
    "match_candidates",
    "match_pairs",
    "match_rebuild_state",
    "custom_locations",
    "contract_articles",
    "wa_templates",
    "storage_objects",
    "offer_photos",
    "record_acl",
    "storage_usage",
    "storage_events",
    "agency_settings",
}

VISIBILITY_TABLES = {
    "clients",
    "listings",
    "demandes",
    "offers",
    "visits",
    "contracts",
}


def _visibility_predicate(table: str, ref: str | None) -> str:
    prefix = f"{ref}." if ref else ""
    outer_id_ref = f"{ref}.id" if ref else f"{table}.id"
    return (
        "("
        "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
        "OR ("
        f"{prefix}agency_id = {AGENCY_DEFAULT_EXPR} "
        "AND ("
        f"{MANAGER_OR_OWNER_EXPR} "
        f"OR {prefix}visibility IS NULL "
        f"OR {prefix}visibility = 'agency' "
        "OR ("
        f"{prefix}visibility = 'restricted' "
        f"AND {ACTOR_ID_EXPR} IS NOT NULL "
        "AND EXISTS ("
        "SELECT 1 FROM record_acl ra "
        f"WHERE ra.table_name = '{table}' "
        f"AND ra.record_id = {outer_id_ref} "
        f"AND ra.user_id = {ACTOR_ID_EXPR}"
        ")"
        ")"
        ")"
        ")"
        ")"
    )


def _rls_predicate_for_table(table: str) -> str:
    if table in VISIBILITY_TABLES:
        return _visibility_predicate(table, None)
    if table == "match_pairs":
        return (
            "("
            "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
            "OR ("
            f"agency_id = {AGENCY_DEFAULT_EXPR} "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_pairs.demande_visibility IS NULL "
            "OR match_pairs.demande_visibility = 'agency' "
            "OR ("
            "match_pairs.demande_visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'demandes' "
            "AND ra.record_id = match_pairs.demande_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ") "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_pairs.offer_visibility IS NULL "
            "OR match_pairs.offer_visibility = 'agency' "
            "OR ("
            "match_pairs.offer_visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'offers' "
            "AND ra.record_id = match_pairs.offer_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ")"
            ")"
            ")"
        )
    if table == "match_candidates":
        return (
            "("
            "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
            "OR ("
            f"agency_id = {AGENCY_DEFAULT_EXPR} "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_candidates.demande_visibility IS NULL "
            "OR match_candidates.demande_visibility = 'agency' "
            "OR ("
            "match_candidates.demande_visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'demandes' "
            "AND ra.record_id = match_candidates.demande_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ") "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_candidates.offer_visibility IS NULL "
            "OR match_candidates.offer_visibility = 'agency' "
            "OR ("
            "match_candidates.offer_visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'offers' "
            "AND ra.record_id = match_candidates.offer_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ")"
            ")"
            ")"
        )
    if table == "match_counts_cache":
        return (
            "("
            "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
            "OR ("
            f"agency_id = {AGENCY_DEFAULT_EXPR} "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_counts_cache.visibility IS NULL "
            "OR match_counts_cache.visibility = 'agency' "
            "OR ("
            "match_counts_cache.visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'clients' "
            "AND ra.record_id = match_counts_cache.client_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ")"
            ")"
            ")"
        )
    return RLS_PREDICATE


def _create_extensions() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def _create_tables() -> None:
    # Core entities.
    op.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id BIGSERIAL PRIMARY KEY,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            family_name TEXT,
            family_name_enc TEXT,
            family_name_search_idx BYTEA[],
            phone TEXT,
            phone_enc TEXT,
            phone_search_idx BYTEA[],
            remarks TEXT,
            remarks_enc TEXT,
            tags TEXT,
            is_vip SMALLINT DEFAULT 0,
            status TEXT DEFAULT 'active',
            owner_user_id BIGINT,
            owner_role TEXT,
            visibility TEXT DEFAULT 'agency',
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            created_loc TEXT,
            updated_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id BIGSERIAL PRIMARY KEY,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            family_name TEXT,
            family_name_enc TEXT,
            family_name_search_idx BYTEA[],
            phone TEXT,
            phone_enc TEXT,
            phone_search_idx BYTEA[],
            remarks TEXT,
            remarks_enc TEXT,
            is_vip SMALLINT DEFAULT 0,
            status TEXT DEFAULT 'available',
            owner_user_id BIGINT,
            owner_role TEXT,
            visibility TEXT DEFAULT 'agency',
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            created_loc TEXT,
            updated_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS demandes (
            id BIGSERIAL PRIMARY KEY,
            client_id BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            type TEXT,
            type_id INTEGER,
            action TEXT,
            action_id INTEGER,
            wilaya TEXT,
            wilaya_id INTEGER,
            locations TEXT,
            locations_enc TEXT,
            beds_min INTEGER NOT NULL DEFAULT 0,
            surface_min NUMERIC NOT NULL DEFAULT 0,
            surface_max NUMERIC NOT NULL DEFAULT 0,
            budget_min NUMERIC NOT NULL DEFAULT 0,
            budget_max NUMERIC NOT NULL DEFAULT 0,
            budget_range numrange DEFAULT numrange(0::numeric, NULL, '[]'),
            surface_range numrange DEFAULT numrange(0::numeric, NULL, '[]'),
            beds_range int4range DEFAULT int4range(0, NULL, '[]'),
            furnished TEXT,
            floor_min INTEGER,
            floor_max INTEGER,
            elevator SMALLINT,
            accessibility_required SMALLINT,
            tags TEXT,
            remarks TEXT,
            remarks_enc TEXT,
            owner_user_id BIGINT,
            owner_role TEXT,
            visibility TEXT DEFAULT 'agency',
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id BIGSERIAL PRIMARY KEY,
            listing_id BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            type TEXT,
            type_id INTEGER,
            action TEXT,
            action_id INTEGER,
            status TEXT NOT NULL DEFAULT 'available',
            wilaya TEXT,
            wilaya_id INTEGER,
            location TEXT,
            location_enc TEXT,
            beds INTEGER,
            surface NUMERIC,
            budget NUMERIC,
            price_negotiable SMALLINT DEFAULT 0,
            price_flex_pct NUMERIC DEFAULT 0,
            price_range numrange,
            furnished TEXT,
            floor INTEGER DEFAULT 0,
            elevator SMALLINT DEFAULT 0,
            accessibility_supported SMALLINT DEFAULT 0,
            link TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            remarks TEXT,
            remarks_enc TEXT,
            owner_user_id BIGINT,
            owner_role TEXT,
            visibility TEXT DEFAULT 'agency',
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)

    # Lookup / metadata.
    op.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS property_types (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            name_ar TEXT,
            requires_floor BOOLEAN NOT NULL DEFAULT FALSE
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            name_ar TEXT
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wilayas (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            code TEXT,
            name_ar TEXT
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_templates (
            id BIGSERIAL PRIMARY KEY,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            name TEXT NOT NULL,
            template TEXT NOT NULL,
            is_default SMALLINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS agency_settings (
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            key TEXT NOT NULL,
            value TEXT,
            updated_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1,
            PRIMARY KEY (agency_id, key)
        )
        """)

    # Locations and junctions.
    op.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            location_id BIGSERIAL PRIMARY KEY,
            location_norm TEXT UNIQUE NOT NULL
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS demande_locations (
            demande_id BIGINT NOT NULL REFERENCES demandes(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            location_id BIGINT NOT NULL REFERENCES locations(location_id),
            PRIMARY KEY (demande_id, location_id)
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS offer_locations (
            offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            location_id BIGINT NOT NULL REFERENCES locations(location_id),
            PRIMARY KEY (offer_id, location_id)
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS custom_locations (
            id BIGSERIAL PRIMARY KEY,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)

    # CRM.
    op.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id BIGSERIAL PRIMARY KEY,
            client_id BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            listing_id BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            scheduled_date DATE NOT NULL,
            scheduled_time TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled',
            notes TEXT,
            notes_enc TEXT,
            owner_user_id BIGINT,
            owner_role TEXT,
            visibility TEXT DEFAULT 'agency',
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id BIGSERIAL PRIMARY KEY,
            client_id BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            listing_id BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            contract_type TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            start_date DATE,
            end_date DATE,
            amount DOUBLE PRECISION,
            amount_enc TEXT,
            deposit DOUBLE PRECISION,
            deposit_enc TEXT,
            terms TEXT,
            terms_enc TEXT,
            notes TEXT,
            notes_enc TEXT,
            owner_user_id BIGINT,
            owner_role TEXT,
            visibility TEXT DEFAULT 'agency',
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_articles (
            id BIGSERIAL PRIMARY KEY,
            contract_id BIGINT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            article_number INTEGER NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            is_standard SMALLINT DEFAULT 0,
            is_required SMALLINT DEFAULT 0,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)

    # Match workspace tables.
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_counts_cache (
            client_id BIGINT PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            count INTEGER NOT NULL DEFAULT 0,
            family_name TEXT,
            phone TEXT,
            visibility TEXT,
            owner_user_id BIGINT,
            computed_at TIMESTAMPTZ,
            is_dirty SMALLINT DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_candidates (
            demande_id BIGINT NOT NULL REFERENCES demandes(id) ON DELETE CASCADE,
            offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            demande_visibility TEXT,
            offer_visibility TEXT,
            demande_owner_user_id BIGINT,
            offer_owner_user_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (demande_id, offer_id)
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_pairs (
            demande_id BIGINT NOT NULL REFERENCES demandes(id) ON DELETE CASCADE,
            offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            demande_visibility TEXT,
            offer_visibility TEXT,
            demande_owner_user_id BIGINT,
            offer_owner_user_id BIGINT,
            score DOUBLE PRECISION NOT NULL,
            rank INTEGER,
            computed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (demande_id, offer_id)
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_rebuild_state (
            scope TEXT NOT NULL,
            scope_id BIGINT NOT NULL,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            pending BOOLEAN NOT NULL DEFAULT FALSE,
            generation BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope, scope_id, agency_id)
        )
        """)

    # Notifications / audit / failures.
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actor TEXT,
            action TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_id TEXT,
            details JSONB,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS task_failures (
            id BIGSERIAL PRIMARY KEY,
            task_id TEXT,
            name TEXT,
            args TEXT,
            kwargs TEXT,
            exception TEXT,
            traceback TEXT,
            failed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            schema_name TEXT,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id BIGSERIAL PRIMARY KEY,
            scope TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            data JSONB,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            user_id BIGINT,
            role TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS notification_reads (
            notification_id BIGINT NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            read_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (notification_id, user_id)
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_security_events (
            id BIGSERIAL PRIMARY KEY,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            user_id BIGINT,
            event_type TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'unknown',
            identifier TEXT,
            reason_code TEXT,
            source_ip TEXT,
            user_agent TEXT,
            request_id TEXT,
            details JSONB,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)

    # Storage / ACL metadata.
    op.execute("""
        CREATE TABLE IF NOT EXISTS storage_objects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            user_id BIGINT NOT NULL,
            role TEXT NOT NULL,
            bucket TEXT NOT NULL,
            object_key TEXT NOT NULL,
            content_type TEXT,
            size_bytes BIGINT,
            checksum TEXT,
            purpose TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_ip TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS offer_photos (
            id BIGSERIAL PRIMARY KEY,
            offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            storage_id UUID NOT NULL REFERENCES storage_objects(id) ON DELETE RESTRICT,
            position INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            row_version BIGINT NOT NULL DEFAULT 1
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS record_acl (
            id BIGSERIAL PRIMARY KEY,
            table_name TEXT NOT NULL,
            record_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS storage_usage (
            agency_id BIGINT PRIMARY KEY,
            total_bytes BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS storage_events (
            id BIGSERIAL PRIMARY KEY,
            storage_id UUID NOT NULL REFERENCES storage_objects(id) ON DELETE CASCADE,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            user_id BIGINT,
            role TEXT,
            event_type TEXT NOT NULL,
            created_ip TEXT,
            details JSONB,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)

    # Core constraints that need guarded CREATE.
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE auth_security_events
            ADD CONSTRAINT chk_auth_security_events_outcome
            CHECK (outcome IN ('attempt', 'success', 'failure', 'unknown'));
        EXCEPTION
            WHEN duplicate_object THEN NULL;
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

    # Optional account-user FKs.
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.accounts_user') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE auth_security_events
            ADD CONSTRAINT fk_auth_security_events_user
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


def _create_search_functions() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_norm_text(input_text TEXT)
        RETURNS TEXT
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT lower(unaccent(coalesce(input_text, '')))
        $$;
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_hex_text_array_to_bytea(p_values TEXT[])
        RETURNS BYTEA[]
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT CASE
                WHEN p_values IS NULL THEN NULL
                ELSE ARRAY(
                    SELECT decode(v, 'hex')
                    FROM unnest(p_values) AS v
                )
            END
        $$;
        """)
    op.execute("DROP FUNCTION IF EXISTS immoapp_hash_trigrams(TEXT)")
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_hash_trigrams(input_text TEXT)
        RETURNS BYTEA[]
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            norm TEXT;
            secret TEXT;
            secrets_text TEXT;
            secrets TEXT[];
            trigram_limit INTEGER;
        BEGIN
            norm := immoapp_norm_text(input_text);
            IF norm = '' THEN
                RETURN ARRAY[]::BYTEA[];
            END IF;

            secrets_text := current_setting('app.ale_search_secrets', true);
            IF secrets_text IS NOT NULL AND secrets_text <> '' THEN
                secrets := array_remove(string_to_array(secrets_text, ';'), '');
            END IF;
            IF secrets IS NULL OR array_length(secrets, 1) IS NULL THEN
                secret := current_setting('app.ale_search_secret', true);
                IF secret IS NULL OR secret = '' THEN
                    RAISE EXCEPTION 'app.ale_search_secret/app.ale_search_secrets is required for immoapp_hash_trigrams()';
                END IF;
                secrets := ARRAY[secret];
            END IF;
            trigram_limit := COALESCE(
                NULLIF(current_setting('app.ale_trigram_limit', true), '')::INTEGER,
                128
            );
            IF trigram_limit < 16 THEN
                trigram_limit := 16;
            END IF;

            RETURN COALESCE(
                (
                    SELECT array_agg(
                        DISTINCT substring(hmac(tri, sec.secret, 'sha256') FROM 1 FOR 12)
                    )
                    FROM (
                        SELECT tri
                        FROM unnest(show_trgm(norm)) AS tri
                        LIMIT trigram_limit
                    ) limited
                    CROSS JOIN unnest(secrets) AS sec(secret)
                ),
                ARRAY[]::BYTEA[]
            );
        END
        $$;
        """)


def _create_guard_triggers() -> None:
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
    op.execute("""
        DO $$
        BEGIN
            CREATE TRIGGER trg_sync_match_cache_client
            AFTER UPDATE OF visibility, owner_user_id, status, deleted_at ON clients
            FOR EACH ROW EXECUTE FUNCTION sync_match_cache_from_client();
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)

    op.execute("""
        CREATE OR REPLACE FUNCTION storage_events_block_mod()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RETURN NULL;
        END;
        $$;
        """)
    op.execute("DROP TRIGGER IF EXISTS storage_events_no_mod ON storage_events")
    op.execute("""
        CREATE TRIGGER storage_events_no_mod
        BEFORE UPDATE OR DELETE ON storage_events
        FOR EACH ROW EXECUTE FUNCTION storage_events_block_mod()
        """)

    op.execute("""
        CREATE OR REPLACE FUNCTION auth_security_events_block_mod()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RETURN NULL;
        END;
        $$;
        """)
    op.execute("DROP TRIGGER IF EXISTS auth_security_events_no_mod ON auth_security_events")
    op.execute("""
        CREATE TRIGGER auth_security_events_no_mod
        BEFORE UPDATE OR DELETE ON auth_security_events
        FOR EACH ROW EXECUTE FUNCTION auth_security_events_block_mod()
        """)


def _apply_acl_defaults() -> None:
    for table in ("clients", "listings", "demandes", "offers", "visits", "contracts"):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN owner_user_id "
            "SET DEFAULT NULLIF(current_setting('app.actor_id', true), '')::bigint"
        )
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN owner_role "
            "SET DEFAULT NULLIF(current_setting('app.actor_role', true), '')"
        )

    for table in VISIBILITY_TABLES:
        op.execute(f"UPDATE {table} SET visibility = 'agency' WHERE visibility IS NULL")
        op.execute(f"""
            DO $$
            BEGIN
                ALTER TABLE {table}
                ADD CONSTRAINT chk_{table}_visibility
                CHECK (visibility IS NULL OR visibility IN ('agency', 'restricted'));
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
            """)

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
        UPDATE match_counts_cache m
        SET visibility = c.visibility,
            owner_user_id = c.owner_user_id
        FROM clients c
        WHERE m.client_id = c.id
          AND (m.visibility IS NULL OR m.owner_user_id IS NULL)
        """)


def _add_account_fk_if_available(table: str, *, on_delete: str = "") -> None:
    on_delete_sql = f" {on_delete.strip()}" if on_delete.strip() else ""
    op.execute(f"""
        DO $$
        BEGIN
            IF to_regclass('public.{table}') IS NULL OR to_regclass('public.accounts_agency') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE {table}
            ADD CONSTRAINT fk_{table}_agency
            FOREIGN KEY (agency_id) REFERENCES accounts_agency(id){on_delete_sql};
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)


def _apply_tenant_isolation() -> None:
    null_ok_fk_tables = {
        "auth_security_events",
        "audit_logs",
        "task_failures",
        "notifications",
        "notification_reads",
    }
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS agency_id BIGINT")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN agency_id SET DEFAULT {AGENCY_DEFAULT_EXPR}")
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_agency_id ON {table}(agency_id)")
        if table in null_ok_fk_tables:
            _add_account_fk_if_available(table, on_delete="ON DELETE SET NULL")
        else:
            _add_account_fk_if_available(table)
        if table in TENANT_TABLES_NOT_NULL:
            op.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM {table} WHERE agency_id IS NULL LIMIT 1) THEN
                        ALTER TABLE {table} ALTER COLUMN agency_id SET NOT NULL;
                    END IF;
                END $$;
                """)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        policy_predicate = _rls_predicate_for_table(table)
        op.execute(f"DROP POLICY IF EXISTS policy_{table}_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY policy_{table}_isolation ON {table}
            USING ({policy_predicate})
            WITH CHECK ({policy_predicate})
            """)

    op.execute("ALTER TABLE audit_logs ALTER COLUMN agency_id DROP NOT NULL")

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM clients
                WHERE deleted_at IS NULL
                  AND phone IS NOT NULL
                  AND btrim(phone) <> ''
                GROUP BY agency_id, phone
                HAVING COUNT(*) > 1
            ) THEN
                RETURN;
            END IF;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_agency_phone_active
            ON clients(agency_id, phone)
            WHERE deleted_at IS NULL AND phone IS NOT NULL AND btrim(phone) <> '';
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM listings
                WHERE deleted_at IS NULL
                  AND phone IS NOT NULL
                  AND btrim(phone) <> ''
                GROUP BY agency_id, phone
                HAVING COUNT(*) > 1
            ) THEN
                RETURN;
            END IF;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_listings_agency_phone_active
            ON listings(agency_id, phone)
            WHERE deleted_at IS NULL AND phone IS NOT NULL AND btrim(phone) <> '';
        END $$;
        """)
    op.execute("ALTER TABLE wa_templates DROP CONSTRAINT IF EXISTS wa_templates_name_key")
    op.execute("DROP INDEX IF EXISTS idx_wa_templates_agency_name")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_wa_templates_agency_name_active
        ON wa_templates(agency_id, name)
        WHERE deleted_at IS NULL
        """)
    op.execute(
        "ALTER TABLE custom_locations DROP CONSTRAINT IF EXISTS custom_locations_name_agency_id_key"
    )
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_locations_agency_name_active
        ON custom_locations(agency_id, name)
        WHERE deleted_at IS NULL
        """)

    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.agency_settings') IS NULL THEN
                RETURN;
            END IF;
            CREATE INDEX IF NOT EXISTS idx_agency_settings_agency_id ON agency_settings(agency_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agency_settings_key_scope
                ON agency_settings(agency_id, key);
            IF to_regclass('public.accounts_agency') IS NOT NULL THEN
                UPDATE agency_settings
                SET agency_id = (
                    SELECT id FROM accounts_agency ORDER BY id LIMIT 1
                )
                WHERE agency_id IS NULL;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM agency_settings WHERE agency_id IS NULL LIMIT 1) THEN
                ALTER TABLE agency_settings DROP CONSTRAINT IF EXISTS agency_settings_pkey;
                BEGIN
                    ALTER TABLE agency_settings
                    ADD CONSTRAINT agency_settings_pkey PRIMARY KEY (agency_id, key);
                EXCEPTION WHEN duplicate_object THEN NULL;
                END;
                ALTER TABLE agency_settings ALTER COLUMN agency_id SET NOT NULL;
            END IF;
        END $$;
        """)


def _create_special_tenant_indexes() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_clients_family_name ON clients(family_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_clients_deleted_at ON clients(deleted_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_clients_phone_search ON clients USING GIN(phone_search_idx)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_clients_name_search ON clients USING GIN(family_name_search_idx)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_clients_active_by_agency "
        "ON clients(agency_id, family_name) "
        "WHERE deleted_at IS NULL AND status = 'active'"
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_listings_phone ON listings(phone)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_listings_family_name ON listings(family_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_listings_deleted_at ON listings(deleted_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_listings_phone_search ON listings USING GIN(phone_search_idx)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_listings_name_search ON listings USING GIN(family_name_search_idx)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_listings_available_by_agency "
        "ON listings(agency_id, family_name) "
        "WHERE deleted_at IS NULL AND status = 'available'"
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_demandes_client ON demandes(client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_demandes_wilaya_id ON demandes(wilaya_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_demandes_deleted_at ON demandes(deleted_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demandes_active_agency_action_wilaya "
        "ON demandes(agency_id, action_id, wilaya_id) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demandes_budget_range_gist "
        "ON demandes USING GIST (agency_id, budget_range)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demandes_strict_matching "
        "ON demandes(agency_id, type_id, action_id) "
        "WHERE type_id IS NOT NULL AND action_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demandes_client_active "
        "ON demandes(client_id, id) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demandes_active_agency_action_type "
        "ON demandes(agency_id, action_id, type_id) "
        "WHERE deleted_at IS NULL"
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_offers_listing ON offers(listing_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_wilaya_type_action_id ON offers(wilaya_id, type_id, action_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_offers_budget ON offers(budget)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_offers_surface ON offers(surface)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_offers_beds ON offers(beds)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_offers_deleted_at ON offers(deleted_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_active_agency_action_wilaya_type "
        "ON offers(agency_id, action_id, wilaya_id, type_id) "
        "WHERE status = 'available' AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_active_agency_action_wilaya_type_v2 "
        "ON offers(agency_id, action_id, wilaya_id, type_id) "
        "WHERE status = 'available' AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_budget_range_gist "
        "ON offers USING GIST (agency_id, price_range)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_offers_surface_btree ON offers(agency_id, surface)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_offers_beds_btree ON offers(agency_id, beds)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_strict_matching "
        "ON offers(agency_id, type_id, action_id) "
        "WHERE type_id IS NOT NULL AND action_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_listing_active "
        "ON offers(listing_id, id) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_active_agency_action_type "
        "ON offers(agency_id, action_id, type_id) "
        "WHERE status = 'available' AND deleted_at IS NULL"
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_loc_norm ON locations(location_norm)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_demande_loc ON demande_locations(location_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_offer_loc ON offer_locations(location_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demande_loc_agency "
        "ON demande_locations(agency_id, location_id, demande_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offer_loc_agency "
        "ON offer_locations(agency_id, location_id, offer_id)"
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_visits_client ON visits(client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_visits_listing ON visits(listing_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_visits_date ON visits(scheduled_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_visits_status ON visits(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_visits_deleted_at ON visits(deleted_at)")

    op.execute("CREATE INDEX IF NOT EXISTS idx_contracts_client ON contracts(client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contracts_listing ON contracts(listing_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contracts_type ON contracts(contract_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contracts_deleted_at ON contracts(deleted_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_contract_articles_contract ON contract_articles(contract_id)"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_failures_failed_at ON task_failures(failed_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_failures_agency ON task_failures(agency_id)")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_scope ON notifications(scope)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_role ON notifications(role)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_agency_id ON notifications(agency_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_reads_user_id ON notification_reads(user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_reads_notification_id "
        "ON notification_reads(notification_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_reads_agency_id ON notification_reads(agency_id)"
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_cache_client_id ON match_counts_cache(client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_cache_dirty ON match_counts_cache(is_dirty)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cache_hot_leads ON match_counts_cache(is_dirty, count DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cache_dirty_agency ON match_counts_cache(agency_id) WHERE is_dirty = 1"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cache_hot_leads_agency "
        "ON match_counts_cache(agency_id, count DESC) "
        "WHERE is_dirty = 0"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_candidates_demande ON match_candidates(demande_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_candidates_offer ON match_candidates(offer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_candidates_agency_id ON match_candidates(agency_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_pairs_demande_score ON match_pairs(demande_id, score DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_match_pairs_offer ON match_pairs(offer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_match_pairs_agency_id ON match_pairs(agency_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_pairs_agency_demande_score "
        "ON match_pairs(agency_id, demande_id, score DESC, offer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_pairs_demande_score_offer "
        "ON match_pairs(demande_id, score DESC, offer_id)"
    )
    op.execute("DROP INDEX IF EXISTS idx_match_rebuild_state_agency")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_rebuild_state_agency_id "
        "ON match_rebuild_state(agency_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_locations_name ON custom_locations(name)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_locations_agency_name_active "
        "ON custom_locations(agency_id, name) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wa_templates_agency_name_active "
        "ON wa_templates(agency_id, name) WHERE deleted_at IS NULL"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_agency "
        "ON auth_security_events(agency_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_agency_id "
        "ON auth_security_events(agency_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_created_at "
        "ON auth_security_events(created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_event_outcome "
        "ON auth_security_events(event_type, outcome, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_user "
        "ON auth_security_events(user_id, created_at DESC)"
    )

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_objects_bucket_key ON storage_objects(bucket, object_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_objects_agency_status ON storage_objects(agency_id, status)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_storage_objects_user ON storage_objects(user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_objects_purpose_created "
        "ON storage_objects(purpose, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_objects_deleted_at "
        "ON storage_objects(deleted_at) WHERE status = 'deleted'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_objects_pending_created "
        "ON storage_objects(created_at) WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_usage_updated ON storage_usage(updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_events_storage_id ON storage_events(storage_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_events_created_at ON storage_events(created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_events_agency_id ON storage_events(agency_id)"
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_offer_photos_offer_id ON offer_photos(offer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_offer_photos_storage_id ON offer_photos(storage_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_offer_photos_agency_id ON offer_photos(agency_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_offer_photos_offer_storage_active "
        "ON offer_photos(offer_id, storage_id) WHERE deleted_at IS NULL"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_record_acl_table_record ON record_acl(table_name, record_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_record_acl_entry ON record_acl(table_name, record_id, user_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_record_acl_user ON record_acl(user_id)")

    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_agency_ts ON audit_logs(agency_id, ts DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_agency_id ON audit_logs(agency_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_ts_desc ON audit_logs(ts DESC)")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_location_trgm "
        "ON offers USING GIN (location gin_trgm_ops) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demandes_locations_trgm "
        "ON demandes USING GIN (locations gin_trgm_ops) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_custom_locations_name_trgm "
        "ON custom_locations USING GIN (name gin_trgm_ops) "
        "WHERE deleted_at IS NULL"
    )


def _seed_meta_defaults() -> None:
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('schema_version', '3')
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """)
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('settings_schema_version', '1')
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """)
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('ale_search_key_version', 'v1')
        ON CONFLICT (key) DO NOTHING
        """)
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('ale_search_key_prev_version', '')
        ON CONFLICT (key) DO NOTHING
        """)
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('ale_key_rotation_at', CURRENT_TIMESTAMP::text)
        ON CONFLICT (key) DO NOTHING
        """)
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('ale_search_rotation_at', CURRENT_TIMESTAMP::text)
        ON CONFLICT (key) DO NOTHING
        """)
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('ale_pii_purge_at', CURRENT_TIMESTAMP::text)
        ON CONFLICT (key) DO NOTHING
        """)


def upgrade() -> None:
    _create_extensions()
    _create_tables()
    _create_search_functions()
    _create_guard_triggers()
    _apply_acl_defaults()
    _apply_tenant_isolation()
    _create_special_tenant_indexes()
    _seed_meta_defaults()


def downgrade() -> None:
    # Baseline upgrade is intentionally non-reversible; rollback is restore-based.
    return None
