"""Move runtime index creation into Alembic migrations.

Revision ID: 20260219_0014
Revises: 20260218_0013
Create Date: 2026-02-19
"""

from __future__ import annotations

from alembic import op

revision = "20260219_0014"
down_revision = "20260218_0013"
branch_labels = None
depends_on = None


_INDEX_DROP_ORDER: tuple[str, ...] = (
    "idx_clients_phone",
    "idx_clients_family_name",
    "idx_clients_deleted_at",
    "idx_clients_phone_search",
    "idx_clients_name_search",
    "idx_clients_active_by_agency",
    "idx_listings_phone",
    "idx_listings_family_name",
    "idx_listings_deleted_at",
    "idx_listings_phone_search",
    "idx_listings_name_search",
    "idx_listings_available_by_agency",
    "idx_demandes_client",
    "idx_demandes_wilaya_id",
    "idx_demandes_deleted_at",
    "idx_demandes_active_agency_action_wilaya",
    "idx_demandes_budget_range_gist",
    "idx_demandes_strict_matching",
    "idx_demandes_client_active",
    "idx_offers_listing",
    "idx_offers_wilaya_type_action_id",
    "idx_offers_budget",
    "idx_offers_surface",
    "idx_offers_beds",
    "idx_offers_deleted_at",
    "idx_offers_active_agency_action_wilaya_type",
    "idx_offers_budget_range_gist",
    "idx_offers_surface_btree",
    "idx_offers_beds_btree",
    "idx_offers_strict_matching",
    "idx_offers_listing_active",
    "idx_loc_norm",
    "idx_demande_loc",
    "idx_offer_loc",
    "idx_locations_name",
    "uq_custom_locations_agency_name_active",
    "idx_visits_client",
    "idx_visits_listing",
    "idx_visits_date",
    "idx_visits_status",
    "idx_visits_deleted_at",
    "idx_contracts_client",
    "idx_contracts_listing",
    "idx_contracts_status",
    "idx_contracts_type",
    "idx_contracts_deleted_at",
    "idx_contract_articles_contract",
    "uq_wa_templates_agency_name_active",
    "idx_task_failures_failed_at",
    "idx_task_failures_agency",
    "idx_notifications_created_at",
    "idx_notifications_user_id",
    "idx_notifications_scope",
    "idx_notifications_role",
    "idx_notifications_agency_id",
    "idx_notification_reads_user_id",
    "idx_notification_reads_notification_id",
    "idx_notification_reads_agency_id",
    "idx_auth_security_events_agency",
    "uq_storage_objects_bucket_key",
    "idx_storage_objects_agency_status",
    "idx_storage_objects_user",
    "idx_storage_objects_purpose_created",
    "idx_storage_objects_deleted_at",
    "idx_storage_objects_pending_created",
    "idx_storage_usage_updated",
    "idx_storage_events_storage_id",
    "idx_storage_events_created_at",
    "idx_storage_events_agency_id",
    "idx_offer_photos_offer_id",
    "idx_offer_photos_storage_id",
    "idx_offer_photos_agency_id",
    "uq_offer_photos_offer_storage_active",
    "idx_record_acl_table_record",
    "uq_record_acl_entry",
    "idx_record_acl_user",
    "idx_cache_client_id",
    "idx_cache_dirty",
    "idx_cache_hot_leads",
    "idx_match_candidates_demande",
    "idx_match_candidates_offer",
    "idx_match_candidates_agency_id",
    "idx_match_pairs_demande_score",
    "idx_match_pairs_offer",
    "idx_match_pairs_agency_id",
    "idx_match_pairs_agency_demande_score",
    "idx_match_pairs_demande_score_offer",
    "idx_cache_dirty_agency",
    "idx_cache_hot_leads_agency",
    "idx_audit_agency_ts",
)


def upgrade() -> None:
    # Core tables
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

    op.execute("CREATE INDEX IF NOT EXISTS idx_loc_norm ON locations(location_norm)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_demande_loc ON demande_locations(location_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_offer_loc ON offer_locations(location_id)")

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

    # Optional/late-added tables
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.custom_locations') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_locations_name ON custom_locations(name)';
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_locations_agency_name_active '
                     || 'ON custom_locations(agency_id, name) WHERE deleted_at IS NULL';
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.wa_templates') IS NOT NULL THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_wa_templates_agency_name_active '
                     || 'ON wa_templates(agency_id, name) WHERE deleted_at IS NULL';
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.auth_security_events') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_auth_security_events_agency '
                     || 'ON auth_security_events(agency_id, created_at DESC)';
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.storage_objects') IS NOT NULL THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_objects_bucket_key '
                     || 'ON storage_objects(bucket, object_key)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_objects_agency_status '
                     || 'ON storage_objects(agency_id, status)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_objects_user ON storage_objects(user_id)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_objects_purpose_created '
                     || 'ON storage_objects(purpose, created_at DESC)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_objects_deleted_at '
                     || 'ON storage_objects(deleted_at) WHERE status = ''deleted''';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_objects_pending_created '
                     || 'ON storage_objects(created_at) WHERE status = ''pending''';
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.storage_usage') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_usage_updated ON storage_usage(updated_at DESC)';
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.storage_events') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_events_storage_id ON storage_events(storage_id)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_events_created_at ON storage_events(created_at DESC)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_storage_events_agency_id ON storage_events(agency_id)';
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.offer_photos') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_offer_photos_offer_id ON offer_photos(offer_id)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_offer_photos_storage_id ON offer_photos(storage_id)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_offer_photos_agency_id ON offer_photos(agency_id)';
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_offer_photos_offer_storage_active '
                     || 'ON offer_photos(offer_id, storage_id) WHERE deleted_at IS NULL';
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.record_acl') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_record_acl_table_record '
                     || 'ON record_acl(table_name, record_id)';
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_record_acl_entry '
                     || 'ON record_acl(table_name, record_id, user_id)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_record_acl_user ON record_acl(user_id)';
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.audit_logs') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_audit_agency_ts ON audit_logs(agency_id, ts DESC)';
            END IF;
        END $$;
        """)


def downgrade() -> None:
    for index_name in _INDEX_DROP_ORDER:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
