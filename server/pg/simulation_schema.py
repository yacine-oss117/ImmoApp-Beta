"""
Simulation schema management helpers.
"""

from __future__ import annotations

import os

from core.data.sql_identifiers import validate_identifier
from core.utils.row_casts import row_int

from .schema import ensure_schema
from .uow import PgSession, admin_transaction, use_schema

SIM_SCHEMA = "sim"

SIM_TABLES = [
    "meta",
    "property_types",
    "actions",
    "wilayas",
    "locations",
    "custom_locations",
    "agency_settings",
    "wa_templates",
    "clients",
    "listings",
    "demandes",
    "offers",
    "demande_locations",
    "offer_locations",
    "visits",
    "contracts",
    "contract_articles",
    "match_counts_cache",
]

_SEQUENCES = [
    ("clients", "id", "clients_id_seq"),
    ("listings", "id", "listings_id_seq"),
    ("demandes", "id", "demandes_id_seq"),
    ("offers", "id", "offers_id_seq"),
    ("custom_locations", "id", "custom_locations_id_seq"),
    ("visits", "id", "visits_id_seq"),
    ("contracts", "id", "contracts_id_seq"),
    ("contract_articles", "id", "contract_articles_id_seq"),
    ("wa_templates", "id", "wa_templates_id_seq"),
    ("locations", "location_id", "locations_location_id_seq"),
]


def _schema_exists(session: PgSession, schema: str) -> bool:
    row = session.execute(
        "SELECT 1 AS present FROM information_schema.schemata WHERE schema_name = %s",
        (schema,),
    ).fetchone()
    return bool(row)


def _grant_sim_schema_access(session: PgSession) -> None:
    """Grant the app role access to the simulation schema."""
    role = os.environ.get("POSTGRES_USER", "")
    if not role:
        return
    validate_identifier(role, kind="role")
    session.execute(f"GRANT USAGE, CREATE ON SCHEMA {SIM_SCHEMA} TO {role}")
    session.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SIM_SCHEMA} TO {role}"
    )
    session.execute(
        f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {SIM_SCHEMA} TO {role}"
    )
    session.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SIM_SCHEMA} "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
    )
    session.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SIM_SCHEMA} "
        f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {role}"
    )


def ensure_sim_schema() -> None:
    """Ensure the simulation schema exists and is initialized."""
    with admin_transaction() as session:
        session.execute(f"CREATE SCHEMA IF NOT EXISTS {SIM_SCHEMA}")
        _grant_sim_schema_access(session)
    with use_schema(SIM_SCHEMA):
        ensure_schema(schema=SIM_SCHEMA)


def drop_sim_schema() -> None:
    """Drop the simulation schema and all of its objects."""
    with admin_transaction() as session:
        session.execute(f"DROP SCHEMA IF EXISTS {SIM_SCHEMA} CASCADE")


def reset_sim_schema() -> None:
    """Recreate a clean simulation schema with all tables."""
    drop_sim_schema()
    ensure_sim_schema()


def clone_public_to_sim() -> dict[str, int]:
    """Clone all public tables into the simulation schema."""
    reset_sim_schema()
    counts: dict[str, int] = {}
    with admin_transaction() as session:
        for table in SIM_TABLES:
            validate_identifier(table, kind="table")
            session.execute(f"INSERT INTO {SIM_SCHEMA}.{table} SELECT * FROM public.{table}")
            row = session.execute(f"SELECT COUNT(*) AS count FROM {SIM_SCHEMA}.{table}").fetchone()
            counts[table] = row_int(row, "count") if row else 0
        _reset_sequences(session)
    return counts


def save_sim_to_public() -> dict[str, int]:
    """Overwrite public data with simulation data (destructive)."""
    with admin_transaction() as session:
        if not _schema_exists(session, SIM_SCHEMA):
            raise RuntimeError("Simulation schema does not exist")
        tables = ", ".join(f"public.{table}" for table in SIM_TABLES)
        session.execute(f"TRUNCATE TABLE {tables} CASCADE")
        counts: dict[str, int] = {}
        for table in SIM_TABLES:
            validate_identifier(table, kind="table")
            session.execute(f"INSERT INTO public.{table} SELECT * FROM {SIM_SCHEMA}.{table}")
            row = session.execute(f"SELECT COUNT(*) AS count FROM public.{table}").fetchone()
            counts[table] = row_int(row, "count") if row else 0
        _reset_sequences(session, schema="public")
        session.execute("UPDATE public.match_counts_cache SET is_dirty = 1")
        session.execute(f"DROP SCHEMA IF EXISTS {SIM_SCHEMA} CASCADE")
    return counts


def simulation_status() -> dict[str, object]:
    """Report simulation schema presence and basic row counts."""
    with admin_transaction() as session:
        if not _schema_exists(session, SIM_SCHEMA):
            return {"exists": False}
        counts = _count_tables(session, ("clients", "listings", "demandes", "offers"))
        return {"exists": True, "counts": counts}


def _count_tables(session: PgSession, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        validate_identifier(table, kind="table")
        row = session.execute(f"SELECT COUNT(*) AS count FROM {SIM_SCHEMA}.{table}").fetchone()
        counts[table] = row_int(row, "count") if row else 0
    return counts


def _reset_sequences(session: PgSession, *, schema: str = SIM_SCHEMA) -> None:
    for table, column, sequence in _SEQUENCES:
        validate_identifier(table, kind="table")
        validate_identifier(column, kind="column")
        validate_identifier(sequence, kind="table")
        session.execute(f"""
            SELECT setval(
                '{schema}.{sequence}',
                COALESCE((SELECT MAX({column}) FROM {schema}.{table}), 0) + 1,
                false
            )
            """)
