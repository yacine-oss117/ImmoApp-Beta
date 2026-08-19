"""
Bootstrap helper: create or resolve a default agency and repair null-tenant rows.

This script is a one-off admin/bootstrap utility, not a normal runtime write path.
It intentionally uses admin SQL so the whole bootstrap can run in one transaction
and then verify tenant integrity before commit.

Usage:
    cd server
    python manage.py shell < pg/migrations/migrate_default_agency.py

Or run as Django management command:
    python manage.py runscript pg.migrations.migrate_default_agency
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from server.pg.tenant_fk_hardening import (
    TenantIntegrityReport,
    assert_report_ok,
    audit_tenant_integrity,
    repair_tenant_integrity,
    report_summary,
)
from server.pg.uow import PgSession, admin_transaction

logger = logging.getLogger(__name__)

_ROOT_TABLES = ("clients", "listings")
_BOOTSTRAP_METADATA_TABLES = ("custom_locations", "wa_templates", "agency_settings", "audit_logs")
_DEFAULT_AGENCY_CODE = "DEFAULT"
_DEFAULT_AGENCY_LABEL = "Default"
_DEFAULT_AGENCY_LEGAL_NAME = "Default Agency"


@dataclass(frozen=True)
class DefaultAgencyBootstrapReport:
    mode: str
    target_agency_id: int
    target_agency_code: str
    created_default_agency: bool
    adopted_manager_user_id: int | None
    root_backfill_counts: dict[str, int]
    repair_report: TenantIntegrityReport

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "target_agency_id": self.target_agency_id,
            "target_agency_code": self.target_agency_code,
            "created_default_agency": self.created_default_agency,
            "adopted_manager_user_id": self.adopted_manager_user_id,
            "root_backfill_counts": dict(self.root_backfill_counts),
            "repair_report": self.repair_report.to_dict(),
        }


def _row_to_dict(row: object | None) -> dict[str, object] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    mapping = getattr(row, "_mapping", None)
    if isinstance(mapping, Mapping):
        return dict(mapping)
    return None


def _as_int(value: object | None, *, context: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            return int(raw)
    raise RuntimeError(f"default_agency_bootstrap: expected integer for {context}, got {value!r}")


def _as_str(value: object | None, *, context: str, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    raise RuntimeError(f"default_agency_bootstrap: expected string-like value for {context}")


def _fetchone(
    session: PgSession, sql: str, params: tuple[object, ...] = ()
) -> dict[str, object] | None:
    row = session.execute(sql, params).fetchone()
    return _row_to_dict(row)


def _fetchall(
    session: PgSession, sql: str, params: tuple[object, ...] = ()
) -> list[dict[str, object]]:
    rows = session.execute(sql, params).fetchall()
    return [_row_to_dict(row) or {} for row in rows]


def _rowcount(session: PgSession, sql: str, params: tuple[object, ...] = ()) -> int:
    result = session.execute(sql, params)
    return int(getattr(result, "rowcount", 0) or 0)


def _table_exists(session: PgSession, table_name: str) -> bool:
    row = _fetchone(session, "SELECT to_regclass(%s) AS table_name", (f"public.{table_name}",))
    return bool(row and row.get("table_name"))


def _table_columns(session: PgSession, table_name: str) -> set[str]:
    if not _table_exists(session, table_name):
        return set()
    rows = _fetchall(
        session,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    return {str(row.get("column_name") or "").strip() for row in rows if row.get("column_name")}


def _require_accounts_tables(session: PgSession) -> None:
    missing = [
        table for table in ("accounts_agency", "accounts_user") if not _table_exists(session, table)
    ]
    if missing:
        raise RuntimeError(
            f"default_agency_bootstrap: missing required tables: {', '.join(missing)}"
        )


def _agency_count(session: PgSession) -> int:
    row = _fetchone(session, "SELECT COUNT(*) AS total FROM accounts_agency")
    return _as_int((row or {}).get("total"), context="accounts_agency.total")


def _find_agency_by_code(session: PgSession, agency_code: str) -> tuple[int, str] | None:
    row = _fetchone(
        session,
        """
        SELECT id, agency_code
        FROM accounts_agency
        WHERE agency_code = %s
        ORDER BY id
        LIMIT 1
        """,
        (agency_code,),
    )
    if not row:
        return None
    return _as_int(row.get("id"), context="accounts_agency.id"), _as_str(
        row.get("agency_code"),
        context="accounts_agency.agency_code",
    )


def _first_agency(session: PgSession) -> tuple[int, str]:
    row = _fetchone(
        session,
        """
        SELECT id, agency_code
        FROM accounts_agency
        ORDER BY id
        LIMIT 1
        """,
    )
    if not row:
        raise RuntimeError("default_agency_bootstrap: expected at least one agency")
    return _as_int(row.get("id"), context="accounts_agency.id"), _as_str(
        row.get("agency_code"),
        context="accounts_agency.agency_code",
    )


def _create_default_agency(session: PgSession) -> tuple[int, str]:
    columns = _table_columns(session, "accounts_agency")
    payload: dict[str, object] = {
        "legal_name": _DEFAULT_AGENCY_LEGAL_NAME,
        "display_name": _DEFAULT_AGENCY_LABEL,
        "agency_code": _DEFAULT_AGENCY_CODE,
        "kbis_number": "",
        "phone_number": "",
        "phone_number_enc": "",
        "email": "",
        "address_line1": "",
        "address_line1_enc": "",
        "address_line2": "",
        "address_line2_enc": "",
        "city": "",
        "city_enc": "",
        "postal_code": "",
        "country": "",
        "is_active": True,
        "max_users": 3,
        "max_managers": 1,
        "max_agents_per_manager": 2,
    }
    insert_columns: list[str] = []
    insert_values_sql: list[str] = []
    params: list[object] = []
    for column_name in payload:
        if column_name not in columns:
            continue
        insert_columns.append(column_name)
        insert_values_sql.append("%s")
        params.append(payload[column_name])
    for timestamp_column in ("created_at", "updated_at"):
        if timestamp_column in columns:
            insert_columns.append(timestamp_column)
            insert_values_sql.append("CURRENT_TIMESTAMP")
    row = _fetchone(
        session,
        f"""
        INSERT INTO accounts_agency ({', '.join(insert_columns)})
        VALUES ({', '.join(insert_values_sql)})
        RETURNING id, agency_code
        """,
        tuple(params),
    )
    if not row:
        raise RuntimeError("default_agency_bootstrap: failed to create default agency")
    return _as_int(row.get("id"), context="accounts_agency.id"), _as_str(
        row.get("agency_code"),
        context="accounts_agency.agency_code",
        default=_DEFAULT_AGENCY_CODE,
    )


def _users_exist_for_agency(session: PgSession, agency_id: int) -> bool:
    row = _fetchone(
        session,
        "SELECT 1 AS exists_flag FROM accounts_user WHERE agency_id = %s LIMIT 1",
        (agency_id,),
    )
    return bool(row and row.get("exists_flag") == 1)


def _adopt_manager_if_needed(session: PgSession, agency_id: int) -> int | None:
    if _users_exist_for_agency(session, agency_id):
        return None
    row = _fetchone(
        session,
        """
        WITH candidate AS (
            SELECT id
            FROM accounts_user
            WHERE role = %s
              AND agency_id IS NULL
            ORDER BY id
            LIMIT 1
        ),
        updated AS (
            UPDATE accounts_user u
            SET agency_id = %s
            FROM candidate c
            WHERE u.id = c.id
            RETURNING u.id
        )
        SELECT id FROM updated
        """,
        ("manager", agency_id),
    )
    if not row:
        return None
    return _as_int(row.get("id"), context="accounts_user.id")


def _backfill_root_rows(session: PgSession, agency_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in _ROOT_TABLES:
        counts[table_name] = _rowcount(
            session,
            f"UPDATE {table_name} SET agency_id = %s WHERE agency_id IS NULL",
            (agency_id,),
        )
    return counts


def _backfill_bootstrap_metadata_rows(session: PgSession, agency_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in _BOOTSTRAP_METADATA_TABLES:
        if not _table_exists(session, table_name):
            counts[table_name] = 0
            continue
        counts[table_name] = _rowcount(
            session,
            f"UPDATE {table_name} SET agency_id = %s WHERE agency_id IS NULL",
            (agency_id,),
        )
    return counts


def _null_agency_counts(session: PgSession, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in tables:
        if not _table_exists(session, table_name):
            counts[table_name] = 0
            continue
        row = _fetchone(
            session,
            f"SELECT COUNT(*) AS total FROM {table_name} WHERE agency_id IS NULL",
        )
        counts[table_name] = _as_int((row or {}).get("total"), context=f"{table_name}.total")
    return counts


def _format_nonzero_counts(counts: dict[str, int]) -> str:
    nonzero = {key: value for key, value in counts.items() if int(value) > 0}
    return ", ".join(f"{key}={value}" for key, value in sorted(nonzero.items()))


def _select_report_target(session: PgSession) -> tuple[int, str]:
    return _find_agency_by_code(session, _DEFAULT_AGENCY_CODE) or _first_agency(session)


def migrate_to_default_agency() -> DefaultAgencyBootstrapReport:
    """Bootstrap tenant ownership for legacy null-tenant rows.

    Returns an internal bootstrap report. The helper is bootstrap-only and runs
    entirely inside one admin transaction.
    """

    with admin_transaction() as session:
        _require_accounts_tables(session)

        agency_count = _agency_count(session)
        pre_audit = audit_tenant_integrity(session)
        created_default_agency = False
        adopted_manager_user_id: int | None = None
        root_backfill_counts = {table_name: 0 for table_name in _ROOT_TABLES}
        metadata_backfill_counts = {table_name: 0 for table_name in _BOOTSTRAP_METADATA_TABLES}

        if agency_count == 0:
            target_agency_id, target_agency_code = _create_default_agency(session)
            created_default_agency = True
        elif agency_count == 1:
            target_agency_id, target_agency_code = _first_agency(session)
        else:
            unresolved_root_counts = _null_agency_counts(session, _ROOT_TABLES)
            unresolved_metadata_counts = _null_agency_counts(session, _BOOTSTRAP_METADATA_TABLES)
            unresolved_counts = {
                **unresolved_root_counts,
                **unresolved_metadata_counts,
            }
            if any(count > 0 for count in unresolved_counts.values()):
                raise RuntimeError(
                    "default_agency_bootstrap: multiple agencies exist and unresolved "
                    f"null-tenant rows remain ({_format_nonzero_counts(unresolved_counts)})"
                )
            target_agency_id, target_agency_code = _select_report_target(session)
            repair_report = pre_audit if pre_audit.ok else repair_tenant_integrity(session)
            assert_report_ok(repair_report)
            mode = "noop" if pre_audit.ok else "applied"
            report = DefaultAgencyBootstrapReport(
                mode=mode,
                target_agency_id=target_agency_id,
                target_agency_code=target_agency_code,
                created_default_agency=False,
                adopted_manager_user_id=None,
                root_backfill_counts=root_backfill_counts,
                repair_report=repair_report,
            )
            logger.info("Default agency bootstrap complete: %s", report.to_dict())
            return report

        adopted_manager_user_id = _adopt_manager_if_needed(session, target_agency_id)
        root_backfill_counts = _backfill_root_rows(session, target_agency_id)
        metadata_backfill_counts = _backfill_bootstrap_metadata_rows(session, target_agency_id)

        repair_report = repair_tenant_integrity(session)
        assert_report_ok(repair_report)

        remaining_counts = _null_agency_counts(session, _ROOT_TABLES + _BOOTSTRAP_METADATA_TABLES)
        if any(count > 0 for count in remaining_counts.values()):
            raise RuntimeError(
                "default_agency_bootstrap: unresolved null-tenant rows remain after repair "
                f"({_format_nonzero_counts(remaining_counts)})"
            )

        mode = "applied"
        if (
            not created_default_agency
            and adopted_manager_user_id is None
            and not any(root_backfill_counts.values())
            and not any(metadata_backfill_counts.values())
            and pre_audit.ok
        ):
            mode = "noop"

        report = DefaultAgencyBootstrapReport(
            mode=mode,
            target_agency_id=target_agency_id,
            target_agency_code=target_agency_code,
            created_default_agency=created_default_agency,
            adopted_manager_user_id=adopted_manager_user_id,
            root_backfill_counts=root_backfill_counts,
            repair_report=repair_report,
        )
        logger.info(
            "Default agency bootstrap complete: target_agency_id=%s target_agency_code=%s "
            "mode=%s created_default=%s adopted_manager_user_id=%s root_backfill=%s metadata_backfill=%s audit=%s",
            target_agency_id,
            target_agency_code,
            mode,
            created_default_agency,
            adopted_manager_user_id,
            root_backfill_counts,
            metadata_backfill_counts,
            report_summary(repair_report),
        )
        return report


if __name__ == "__main__":
    import django

    django.setup()

    report = migrate_to_default_agency()
    print(f"Migration complete: {report.to_dict()}")
