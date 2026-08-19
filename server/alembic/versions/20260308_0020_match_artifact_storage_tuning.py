"""Tune autovacuum and autoanalyze for match artifact tables.

Revision ID: 20260308_0020
Revises: 20260303_0019
Create Date: 2026-03-08
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260308_0020"
down_revision = "20260303_0019"
branch_labels = None
depends_on = None

_SET_OPTIONS = """
(
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 2000,
    autovacuum_vacuum_insert_scale_factor = 0.05,
    autovacuum_vacuum_insert_threshold = 5000,
    autovacuum_analyze_scale_factor = 0.01,
    autovacuum_analyze_threshold = 1000
)
"""

_RESET_OPTIONS = """
(
    autovacuum_vacuum_scale_factor,
    autovacuum_vacuum_threshold,
    autovacuum_vacuum_insert_scale_factor,
    autovacuum_vacuum_insert_threshold,
    autovacuum_analyze_scale_factor,
    autovacuum_analyze_threshold
)
"""


def _apply(table: str) -> None:
    op.execute(f"ALTER TABLE IF EXISTS {table} SET {_SET_OPTIONS}")
    op.execute(f"""
        DO $$
        DECLARE
            child regclass;
        BEGIN
            FOR child IN
                SELECT i.inhrelid::regclass
                FROM pg_inherits i
                JOIN pg_class p ON p.oid = i.inhparent
                JOIN pg_namespace n ON n.oid = p.relnamespace
                WHERE n.nspname = current_schema()
                  AND p.relname = '{table}'
            LOOP
                EXECUTE format('ALTER TABLE %s SET {_SET_OPTIONS}', child);
            END LOOP;
        END $$;
        """)


def _reset(table: str) -> None:
    op.execute(f"ALTER TABLE IF EXISTS {table} RESET {_RESET_OPTIONS}")
    op.execute(f"""
        DO $$
        DECLARE
            child regclass;
        BEGIN
            FOR child IN
                SELECT i.inhrelid::regclass
                FROM pg_inherits i
                JOIN pg_class p ON p.oid = i.inhparent
                JOIN pg_namespace n ON n.oid = p.relnamespace
                WHERE n.nspname = current_schema()
                  AND p.relname = '{table}'
            LOOP
                EXECUTE format('ALTER TABLE %s RESET {_RESET_OPTIONS}', child);
            END LOOP;
        END $$;
        """)


def upgrade() -> None:
    _apply("match_candidates")
    _apply("match_pairs")


def downgrade() -> None:
    _reset("match_candidates")
    _reset("match_pairs")
