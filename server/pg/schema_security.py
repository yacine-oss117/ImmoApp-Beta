"""
Security schema verification helpers for tenant isolation.
"""

from __future__ import annotations

import os

from core.data.sql_identifiers import validate_identifier

from .schema_tenant import (
    AGENCY_DEFAULT_EXPR,
    TENANT_TABLES_NULL_OK,
    rls_predicate_for_table,
)
from .schema_tenant_constants import (
    DB_RLS_MANAGED_TABLES,
    TABLE_AGENCY_ID_DEFAULT_OVERRIDES,
)
from .uow import PgSession


def verify_security_schema(session: PgSession) -> list[str]:
    """Return a list of schema isolation violations."""
    issues: list[str] = []
    accounts_agency_exists = _accounts_agency_exists(session)

    for table in DB_RLS_MANAGED_TABLES:
        validate_identifier(table, allowed=set(DB_RLS_MANAGED_TABLES), kind="table")

        row = session.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = %s",
            (table,),
        ).fetchone()
        if not row:
            issues.append(f"{table}: table not found")
            continue
        if not row.get("relrowsecurity"):
            issues.append(f"{table}: RLS disabled")
        if not row.get("relforcerowsecurity"):
            issues.append(f"{table}: FORCE RLS disabled")

        # Verify policy name and expressions, not just existence
        expected_policy_name = f"policy_{table}_isolation"
        policy_row = session.execute(
            """
            SELECT p.polname,
                   pg_get_expr(p.polqual, p.polrelid) AS using_expr,
                   pg_get_expr(p.polwithcheck, p.polrelid) AS withcheck_expr
            FROM pg_policy p
            JOIN pg_class c ON c.oid = p.polrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s AND p.polname = %s
            """,
            (table, expected_policy_name),
        ).fetchone()
        if not policy_row:
            issues.append(f"{table}: missing RLS policy '{expected_policy_name}'")
        else:
            # Verify policy expressions match expected predicate
            table_name = table

            def _norm_expr(s: str, table_name: str = table_name) -> str:
                """Normalize expression for comparison: remove casts, parens, whitespace."""
                s = (
                    s.replace("::text", "")
                    .replace("::bigint", "")
                    .replace("::boolean", "")
                    .replace("::integer", "")
                    .replace('"', "")
                )
                s = s.replace("(", "").replace(")", "")
                s = s.replace("public.", "")
                s = s.replace(f"{table_name}.", "")
                return "".join(s.split()).lower()

            # Expected RLS predicate: superuser OR agency_id matches current context
            # PostgreSQL stores as: (NULLIF(is_superuser)::boolean = true) OR (agency_id = NULLIF(agency_id)::bigint)
            expected_norm = _norm_expr(rls_predicate_for_table(table))

            using_expr = str(policy_row.get("using_expr") or "")
            if using_expr and _norm_expr(using_expr) != expected_norm:
                issues.append(f"{table}: policy USING expression mismatch: {using_expr}")

            withcheck_expr = str(policy_row.get("withcheck_expr") or "")
            if withcheck_expr and _norm_expr(withcheck_expr) != expected_norm:
                issues.append(f"{table}: policy WITH CHECK expression mismatch: {withcheck_expr}")

        default_row = session.execute(
            """
            SELECT pg_get_expr(ad.adbin, ad.adrelid) AS default_expr
            FROM pg_attrdef ad
            JOIN pg_attribute a ON a.attrelid = ad.adrelid AND a.attnum = ad.adnum
            JOIN pg_class c ON c.oid = ad.adrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s AND a.attname = 'agency_id'
            """,
            (table,),
        ).fetchone()

        default_expr = str((default_row or {}).get("default_expr") or "")

        def _norm(s: str) -> str:
            # normalize whitespace and harmless ::text casts that PostgreSQL may inject
            s = s.replace("::text", "")
            # pg_get_expr may add/remove parentheses; do not treat that as a mismatch
            s = s.replace("(", "").replace(")", "")
            return "".join(s.split())

        expected_default_expr = TABLE_AGENCY_ID_DEFAULT_OVERRIDES.get(table, AGENCY_DEFAULT_EXPR)
        # PostgreSQL may render this with or without parentheses and with extra ::text casts
        if expected_default_expr is None:
            if default_expr:
                issues.append(f"{table}: agency_id DEFAULT mismatch: {default_expr}")
        elif _norm(default_expr) != _norm(expected_default_expr):
            issues.append(f"{table}: agency_id DEFAULT mismatch: {default_expr}")

        index_name = f"idx_{table}_agency_id"
        index_row = session.execute(
            "SELECT count(*) AS count FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = %s AND indexname = %s",
            (table, index_name),
        ).fetchone()
        if not index_row or (index_row.get("count") or 0) == 0:
            issues.append(f"{table}: missing agency_id index")

        null_row = session.execute(
            f"SELECT 1 FROM {table} WHERE agency_id IS NULL LIMIT 1"
        ).fetchone()
        if table not in TENANT_TABLES_NULL_OK and null_row is not None:
            issues.append(f"{table}: contains NULL agency_id rows")

        if accounts_agency_exists and not _has_fk(session, table):
            issues.append(f"{table}: missing agency_id FK to accounts_agency")

    app_user = os.environ.get("POSTGRES_USER")
    if app_user:
        role = session.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s",
            (app_user,),
        ).fetchone()
        if role and (role.get("rolsuper") or role.get("rolbypassrls")):
            issues.append(f"{app_user}: role is superuser or BYPASSRLS")

    return issues


def assert_security_schema(session: PgSession) -> None:
    """Raise if schema isolation checks fail."""
    issues = verify_security_schema(session)
    if issues:
        raise RuntimeError("Security schema audit failed:\n" + "\n".join(issues))


def _accounts_agency_exists(session: PgSession) -> bool:
    row = session.execute("SELECT to_regclass('public.accounts_agency') AS name").fetchone()
    return bool(row and row.get("name"))


def _has_fk(session: PgSession, table: str) -> bool:
    row = session.execute(
        "SELECT 1 FROM pg_constraint WHERE conname = %s",
        (f"fk_{table}_agency",),
    ).fetchone()
    return row is not None
