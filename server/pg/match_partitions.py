"""Partition rollout helpers for match cache tables."""

from __future__ import annotations

from dataclasses import dataclass

from .schema_tenant_constants import AGENCY_DEFAULT_EXPR
from .schema_tenant_predicates import rls_predicate_for_table
from .uow import PgSession

_MATCH_ARTIFACT_STORAGE_OPTIONS = (
    "autovacuum_vacuum_scale_factor = 0.02",
    "autovacuum_vacuum_threshold = 2000",
    "autovacuum_vacuum_insert_scale_factor = 0.05",
    "autovacuum_vacuum_insert_threshold = 5000",
    "autovacuum_analyze_scale_factor = 0.01",
    "autovacuum_analyze_threshold = 1000",
)


@dataclass(frozen=True)
class MatchPartitionRolloutResult:
    candidates_partitioned: bool
    pairs_partitioned: bool


def _is_partitioned(session: PgSession, table: str) -> bool:
    row = session.execute(
        """
        SELECT c.relkind = 'p' AS is_partitioned
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = %s
        """,
        (table,),
    ).fetchone()
    return bool((row or {}).get("is_partitioned"))


def _table_exists(session: PgSession, table: str) -> bool:
    row = session.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = %s
        ) AS table_exists
        """,
        (table,),
    ).fetchone()
    return bool((row or {}).get("table_exists"))


def _create_candidates_new(session: PgSession, partitions: int) -> None:
    session.execute("""
        CREATE TABLE IF NOT EXISTS match_candidates_new (
            demande_id BIGINT NOT NULL,
            offer_id BIGINT NOT NULL,
            agency_id BIGINT NOT NULL DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            demande_visibility TEXT,
            offer_visibility TEXT,
            demande_owner_user_id BIGINT,
            offer_owner_user_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (demande_id, offer_id),
            CONSTRAINT fk_match_candidates_new_demande
                FOREIGN KEY (agency_id, demande_id) REFERENCES demandes(agency_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_match_candidates_new_offer
                FOREIGN KEY (agency_id, offer_id) REFERENCES offers(agency_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_match_candidates_new_agency
                FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
        ) PARTITION BY HASH (demande_id)
        """)
    for i in range(partitions):
        session.execute(f"""
            CREATE TABLE IF NOT EXISTS match_candidates_new_p{i:02d}
            PARTITION OF match_candidates_new
            FOR VALUES WITH (MODULUS {partitions}, REMAINDER {i})
            """)
    _apply_match_table_storage_settings(session, "match_candidates_new")
    for i in range(partitions):
        _apply_match_table_storage_settings(session, f"match_candidates_new_p{i:02d}")


def _create_pairs_new(session: PgSession, partitions: int) -> None:
    session.execute("""
        CREATE TABLE IF NOT EXISTS match_pairs_new (
            demande_id BIGINT NOT NULL,
            offer_id BIGINT NOT NULL,
            agency_id BIGINT NOT NULL DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            demande_visibility TEXT,
            offer_visibility TEXT,
            demande_owner_user_id BIGINT,
            offer_owner_user_id BIGINT,
            score DOUBLE PRECISION NOT NULL,
            rank INTEGER,
            computed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (demande_id, offer_id),
            CONSTRAINT fk_match_pairs_new_demande
                FOREIGN KEY (agency_id, demande_id) REFERENCES demandes(agency_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_match_pairs_new_offer
                FOREIGN KEY (agency_id, offer_id) REFERENCES offers(agency_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_match_pairs_new_agency
                FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
        ) PARTITION BY HASH (demande_id)
        """)
    for i in range(partitions):
        session.execute(f"""
            CREATE TABLE IF NOT EXISTS match_pairs_new_p{i:02d}
            PARTITION OF match_pairs_new
            FOR VALUES WITH (MODULUS {partitions}, REMAINDER {i})
            """)
    _apply_match_table_storage_settings(session, "match_pairs_new")
    for i in range(partitions):
        _apply_match_table_storage_settings(session, f"match_pairs_new_p{i:02d}")


def _apply_match_table_storage_settings(session: PgSession, table: str) -> None:
    options_sql = ", ".join(_MATCH_ARTIFACT_STORAGE_OPTIONS)
    session.execute(f"ALTER TABLE {table} SET ({options_sql})")
    child_rows = session.execute(
        """
        SELECT child.relname AS table_name
        FROM pg_inherits i
        JOIN pg_class parent ON parent.oid = i.inhparent
        JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
        JOIN pg_class child ON child.oid = i.inhrelid
        WHERE parent_ns.nspname = current_schema()
          AND parent.relname = %s
        ORDER BY child.relname
        """,
        (table,),
    ).fetchall()
    for row in child_rows:
        child_table = str((row or {}).get("table_name") or "").strip()
        if child_table:
            session.execute(f"ALTER TABLE {child_table} SET ({options_sql})")


def _swap_candidates(session: PgSession) -> None:
    session.execute("""
        INSERT INTO match_candidates_new (
            demande_id,
            offer_id,
            agency_id,
            demande_visibility,
            offer_visibility,
            demande_owner_user_id,
            offer_owner_user_id,
            created_at
        )
        SELECT
            demande_id,
            offer_id,
            agency_id,
            demande_visibility,
            offer_visibility,
            demande_owner_user_id,
            offer_owner_user_id,
            created_at
        FROM match_candidates
        """)
    session.execute("DROP TABLE match_candidates")
    session.execute("ALTER TABLE match_candidates_new RENAME TO match_candidates")


def _swap_pairs(session: PgSession) -> None:
    session.execute("""
        INSERT INTO match_pairs_new (
            demande_id,
            offer_id,
            agency_id,
            demande_visibility,
            offer_visibility,
            demande_owner_user_id,
            offer_owner_user_id,
            score,
            rank,
            computed_at
        )
        SELECT
            demande_id,
            offer_id,
            agency_id,
            demande_visibility,
            offer_visibility,
            demande_owner_user_id,
            offer_owner_user_id,
            score,
            rank,
            computed_at
        FROM match_pairs
        """)
    session.execute("DROP TABLE match_pairs")
    session.execute("ALTER TABLE match_pairs_new RENAME TO match_pairs")


def _create_match_rollout_indexes(session: PgSession) -> None:
    session.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_candidates_demande ON match_candidates(demande_id)"
    )
    session.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_candidates_offer ON match_candidates(offer_id)"
    )
    session.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_candidates_agency_id ON match_candidates(agency_id)"
    )
    session.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_pairs_demande_score ON match_pairs(demande_id, score DESC)"
    )
    session.execute("CREATE INDEX IF NOT EXISTS idx_match_pairs_offer ON match_pairs(offer_id)")
    session.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_pairs_agency_id ON match_pairs(agency_id)"
    )
    session.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_pairs_agency_demande_score "
        "ON match_pairs(agency_id, demande_id, score DESC, offer_id)"
    )
    session.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_pairs_demande_score_offer "
        "ON match_pairs(demande_id, score DESC, offer_id)"
    )


def _reapply_match_table_security(session: PgSession) -> None:
    for table in ("match_candidates", "match_pairs"):
        session.execute(
            f"ALTER TABLE {table} ALTER COLUMN agency_id SET DEFAULT {AGENCY_DEFAULT_EXPR}"
        )
        session.execute(f"ALTER TABLE {table} ALTER COLUMN agency_id SET NOT NULL")
        session.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_agency_id ON {table}(agency_id)")
        session.execute(f"""
            DO $$
            BEGIN
                IF to_regclass('public.accounts_agency') IS NULL THEN
                    RETURN;
                END IF;
                ALTER TABLE {table}
                ADD CONSTRAINT fk_{table}_agency
                FOREIGN KEY (agency_id) REFERENCES accounts_agency(id);
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
            """)
        session.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        session.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        predicate = rls_predicate_for_table(table)
        session.execute(f"DROP POLICY IF EXISTS policy_{table}_isolation ON {table}")
        session.execute(f"""
            CREATE POLICY policy_{table}_isolation ON {table}
            USING ({predicate})
            WITH CHECK ({predicate})
            """)


def rollout_match_partitions(
    session: PgSession, *, partitions: int = 16
) -> MatchPartitionRolloutResult:
    """
    Convert `match_candidates` and `match_pairs` to HASH-partitioned tables.

    This function is explicit/opt-in and should run during a maintenance window.
    """
    if partitions <= 0:
        raise ValueError("partitions must be a positive integer")

    candidates_changed = False
    pairs_changed = False

    if _table_exists(session, "match_candidates") and not _is_partitioned(
        session, "match_candidates"
    ):
        _create_candidates_new(session, partitions)
        _swap_candidates(session)
        candidates_changed = True

    if _table_exists(session, "match_pairs") and not _is_partitioned(session, "match_pairs"):
        _create_pairs_new(session, partitions)
        _swap_pairs(session)
        pairs_changed = True

    if candidates_changed or pairs_changed:
        # Recreate match table indexes and RLS policies on the new physical tables.
        _create_match_rollout_indexes(session)
        _reapply_match_table_security(session)
    if _table_exists(session, "match_candidates"):
        _apply_match_table_storage_settings(session, "match_candidates")
    if _table_exists(session, "match_pairs"):
        _apply_match_table_storage_settings(session, "match_pairs")

    return MatchPartitionRolloutResult(
        candidates_partitioned=candidates_changed,
        pairs_partitioned=pairs_changed,
    )


__all__ = ["MatchPartitionRolloutResult", "rollout_match_partitions"]
