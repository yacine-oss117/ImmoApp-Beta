"""Add tenant-qualified unique constraints and composite foreign keys.

Revision ID: 20260309_0022
Revises: 20260309_0021
Create Date: 2026-03-09
"""

from __future__ import annotations

from alembic import op

revision = "20260309_0022"
down_revision = "20260309_0021"
branch_labels = None
depends_on = None


def _accounts_agency_exists() -> bool:
    row = (
        op.get_bind()
        .exec_driver_sql("SELECT to_regclass('public.accounts_agency') AS table_name")
        .fetchone()
    )
    return bool(getattr(row, "_mapping", {}).get("table_name") if row is not None else None)


def _create_parent_unique_index(name: str, table: str) -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table}(agency_id, id)"
        )
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}'
            ) THEN
                ALTER TABLE {table}
                ADD CONSTRAINT {name} UNIQUE USING INDEX {name};
            END IF;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)


def _add_fk_not_valid(table: str, name: str, cols: str, parent: str, parent_cols: str) -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}'
            ) THEN
                ALTER TABLE {table}
                ADD CONSTRAINT {name}
                FOREIGN KEY ({cols})
                REFERENCES {parent}({parent_cols})
                ON DELETE CASCADE
                NOT VALID;
            END IF;
        END $$;
        """)
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def _drop_constraint_if_exists(table: str, name: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")


def upgrade() -> None:
    if not _accounts_agency_exists():
        return
    _create_parent_unique_index("uq_listings_agency_id_id", "listings")
    _create_parent_unique_index("uq_demandes_agency_id_id", "demandes")
    _create_parent_unique_index("uq_offers_agency_id_id", "offers")
    _create_parent_unique_index("uq_contracts_agency_id_id", "contracts")

    _add_fk_not_valid(
        "demandes",
        "fk_demandes_client_tenant",
        "agency_id, client_id",
        "clients",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "offers",
        "fk_offers_listing_tenant",
        "agency_id, listing_id",
        "listings",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "visits",
        "fk_visits_client_tenant",
        "agency_id, client_id",
        "clients",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "visits",
        "fk_visits_listing_tenant",
        "agency_id, listing_id",
        "listings",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "contracts",
        "fk_contracts_client_tenant",
        "agency_id, client_id",
        "clients",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "contracts",
        "fk_contracts_listing_tenant",
        "agency_id, listing_id",
        "listings",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "contract_articles",
        "fk_contract_articles_contract_tenant",
        "agency_id, contract_id",
        "contracts",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "demande_locations",
        "fk_demande_locations_demande_tenant",
        "agency_id, demande_id",
        "demandes",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "offer_locations",
        "fk_offer_locations_offer_tenant",
        "agency_id, offer_id",
        "offers",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "offer_photos",
        "fk_offer_photos_offer_tenant",
        "agency_id, offer_id",
        "offers",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "match_candidates",
        "fk_match_candidates_demande_tenant",
        "agency_id, demande_id",
        "demandes",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "match_candidates",
        "fk_match_candidates_offer_tenant",
        "agency_id, offer_id",
        "offers",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "match_pairs",
        "fk_match_pairs_demande_tenant",
        "agency_id, demande_id",
        "demandes",
        "agency_id, id",
    )
    _add_fk_not_valid(
        "match_pairs",
        "fk_match_pairs_offer_tenant",
        "agency_id, offer_id",
        "offers",
        "agency_id, id",
    )

    _drop_constraint_if_exists("demandes", "demandes_client_id_fkey")
    _drop_constraint_if_exists("offers", "offers_listing_id_fkey")
    _drop_constraint_if_exists("visits", "visits_client_id_fkey")
    _drop_constraint_if_exists("visits", "visits_listing_id_fkey")
    _drop_constraint_if_exists("contracts", "contracts_client_id_fkey")
    _drop_constraint_if_exists("contracts", "contracts_listing_id_fkey")
    _drop_constraint_if_exists("contract_articles", "contract_articles_contract_id_fkey")
    _drop_constraint_if_exists("demande_locations", "demande_locations_demande_id_fkey")
    _drop_constraint_if_exists("offer_locations", "offer_locations_offer_id_fkey")
    _drop_constraint_if_exists("offer_photos", "offer_photos_offer_id_fkey")
    _drop_constraint_if_exists("match_candidates", "match_candidates_demande_id_fkey")
    _drop_constraint_if_exists("match_candidates", "match_candidates_offer_id_fkey")
    _drop_constraint_if_exists("match_pairs", "match_pairs_demande_id_fkey")
    _drop_constraint_if_exists("match_pairs", "match_pairs_offer_id_fkey")


def downgrade() -> None:
    if not _accounts_agency_exists():
        return
