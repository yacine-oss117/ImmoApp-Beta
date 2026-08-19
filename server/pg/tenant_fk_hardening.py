"""Audit and repair helpers for tenant-qualified foreign-key hardening."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class TenantIntegrityFinding:
    table_name: str
    issue_code: str
    row_count: int
    sample_ids: list[str]


@dataclass(frozen=True)
class TenantIntegrityReport:
    generated_at: str
    ok: bool
    findings: list[TenantIntegrityFinding]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "ok": self.ok,
            "findings": [asdict(finding) for finding in self.findings],
        }


SqlConn = Any

_ROOT_TABLES = ("clients", "listings")
_SINGLE_PARENT_TABLES: tuple[tuple[str, str, str, str], ...] = (
    ("demandes", "id", "client_id", "clients"),
    ("offers", "id", "listing_id", "listings"),
    ("contract_articles", "id", "contract_id", "contracts"),
    ("demande_locations", "demande_id || ':' || location_id", "demande_id", "demandes"),
    ("offer_locations", "offer_id || ':' || location_id", "offer_id", "offers"),
    ("offer_photos", "id", "offer_id", "offers"),
)
_DUAL_PARENT_TABLES: tuple[tuple[str, str], ...] = (
    ("visits", "id"),
    ("contracts", "id"),
)
_ARTIFACT_TABLES = ("match_candidates", "match_pairs")
_CACHE_TABLE = "match_counts_cache"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _exec(conn: SqlConn, sql: str, params: tuple[object, ...] = ()) -> Any:
    if hasattr(conn, "exec_driver_sql"):
        return conn.exec_driver_sql(sql, params)
    return conn.execute(sql, params)


def _row_to_dict(row: object | None) -> dict[str, object] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return dict(mapping)
    try:
        return dict(row)  # type: ignore[arg-type]
    except Exception:
        return None


def _fetchone(conn: SqlConn, sql: str, params: tuple[object, ...] = ()) -> dict[str, object] | None:
    row = _exec(conn, sql, params).fetchone()
    return _row_to_dict(row)


def _fetchall(conn: SqlConn, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    rows = _exec(conn, sql, params).fetchall()
    return [_row_to_dict(row) or {} for row in rows]


def _rowcount(conn: SqlConn, sql: str, params: tuple[object, ...] = ()) -> int:
    result = _exec(conn, sql, params)
    rowcount = getattr(result, "rowcount", None)
    return int(rowcount or 0)


def _sample_ids(
    conn: SqlConn,
    *,
    table: str,
    id_expr: str,
    where_sql: str,
    joins_sql: str = "",
) -> list[str]:
    rows = _fetchall(
        conn,
        f"""
        SELECT ({id_expr})::text AS sample_id
        FROM {table} t
        {joins_sql}
        WHERE {where_sql}
        ORDER BY 1
        LIMIT 5
        """,
    )
    return [
        str(row.get("sample_id") or "") for row in rows if str(row.get("sample_id") or "").strip()
    ]


def _exists(conn: SqlConn, *, table: str, where_sql: str, joins_sql: str = "") -> bool:
    row = _fetchone(
        conn,
        f"""
        SELECT 1 AS exists_flag
        FROM {table} t
        {joins_sql}
        WHERE {where_sql}
        LIMIT 1
        """,
    )
    return row is not None


def _count(conn: SqlConn, *, table: str, where_sql: str, joins_sql: str = "") -> int:
    row = _fetchone(
        conn,
        f"""
        SELECT COUNT(*) AS total
        FROM {table} t
        {joins_sql}
        WHERE {where_sql}
        """,
    )
    return int((row or {}).get("total") or 0)


def _append_finding(
    findings: list[TenantIntegrityFinding],
    *,
    conn: SqlConn,
    table: str,
    issue_code: str,
    id_expr: str,
    where_sql: str,
    joins_sql: str = "",
) -> None:
    if not _exists(conn, table=table, where_sql=where_sql, joins_sql=joins_sql):
        return
    total = _count(conn, table=table, where_sql=where_sql, joins_sql=joins_sql)
    findings.append(
        TenantIntegrityFinding(
            table_name=table,
            issue_code=issue_code,
            row_count=total,
            sample_ids=_sample_ids(
                conn,
                table=table,
                id_expr=id_expr,
                where_sql=where_sql,
                joins_sql=joins_sql,
            ),
        )
    )


def _audit_root_tables(conn: SqlConn, findings: list[TenantIntegrityFinding]) -> None:
    for table in _ROOT_TABLES:
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="ROOT_NULL_AGENCY",
            id_expr="t.id",
            where_sql="t.agency_id IS NULL",
        )
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="ROOT_INVALID_AGENCY",
            id_expr="t.id",
            joins_sql="LEFT JOIN accounts_agency a ON a.id = t.agency_id",
            where_sql="t.agency_id IS NOT NULL AND a.id IS NULL",
        )


def _audit_single_parent(conn: SqlConn, findings: list[TenantIntegrityFinding]) -> None:
    for table, id_expr, parent_id_col, parent_table in _SINGLE_PARENT_TABLES:
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="PARENT_MISSING",
            id_expr=id_expr,
            where_sql=f"NOT EXISTS (SELECT 1 FROM {parent_table} p WHERE p.id = t.{parent_id_col})",
        )
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="TENANT_MISMATCH",
            id_expr=id_expr,
            where_sql=(
                f"EXISTS (SELECT 1 FROM {parent_table} p "
                f"WHERE p.id = t.{parent_id_col} AND t.agency_id IS DISTINCT FROM p.agency_id)"
            ),
        )


def _audit_dual_parent(conn: SqlConn, findings: list[TenantIntegrityFinding]) -> None:
    for table, id_expr in _DUAL_PARENT_TABLES:
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="DUAL_PARENT_MISSING",
            id_expr=f"t.{id_expr}",
            where_sql=(
                "NOT EXISTS (SELECT 1 FROM clients c WHERE c.id = t.client_id) "
                "OR NOT EXISTS (SELECT 1 FROM listings l WHERE l.id = t.listing_id)"
            ),
        )
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="DUAL_PARENT_DISAGREE",
            id_expr=f"t.{id_expr}",
            where_sql=(
                "EXISTS ("
                "SELECT 1 "
                "FROM clients c, listings l "
                "WHERE c.id = t.client_id "
                "AND l.id = t.listing_id "
                "AND c.agency_id IS DISTINCT FROM l.agency_id"
                ")"
            ),
        )
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="TENANT_MISMATCH",
            id_expr=f"t.{id_expr}",
            where_sql=(
                "EXISTS ("
                "SELECT 1 "
                "FROM clients c, listings l "
                "WHERE c.id = t.client_id "
                "AND l.id = t.listing_id "
                "AND c.agency_id = l.agency_id "
                "AND t.agency_id IS DISTINCT FROM c.agency_id"
                ")"
            ),
        )


def _audit_artifacts(conn: SqlConn, findings: list[TenantIntegrityFinding]) -> None:
    for table in _ARTIFACT_TABLES:
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="ARTIFACT_PARENT_MISSING",
            id_expr="t.demande_id || ':' || t.offer_id",
            where_sql=(
                "NOT EXISTS (SELECT 1 FROM demandes d WHERE d.id = t.demande_id) "
                "OR NOT EXISTS (SELECT 1 FROM offers o WHERE o.id = t.offer_id)"
            ),
        )
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="ARTIFACT_PARENT_DISAGREE",
            id_expr="t.demande_id || ':' || t.offer_id",
            where_sql=(
                "EXISTS ("
                "SELECT 1 "
                "FROM demandes d, offers o "
                "WHERE d.id = t.demande_id "
                "AND o.id = t.offer_id "
                "AND d.agency_id IS DISTINCT FROM o.agency_id"
                ")"
            ),
        )
        _append_finding(
            findings,
            conn=conn,
            table=table,
            issue_code="TENANT_MISMATCH",
            id_expr="t.demande_id || ':' || t.offer_id",
            where_sql=(
                "EXISTS ("
                "SELECT 1 "
                "FROM demandes d, offers o "
                "WHERE d.id = t.demande_id "
                "AND o.id = t.offer_id "
                "AND d.agency_id = o.agency_id "
                "AND t.agency_id IS DISTINCT FROM d.agency_id"
                ")"
            ),
        )


def _audit_cache(conn: SqlConn, findings: list[TenantIntegrityFinding]) -> None:
    _append_finding(
        findings,
        conn=conn,
        table=_CACHE_TABLE,
        issue_code="CACHE_CLIENT_MISSING",
        id_expr="coalesce(t.agency_id::text, 'null') || ':' || t.client_id",
        where_sql="NOT EXISTS (SELECT 1 FROM clients c WHERE c.id = t.client_id)",
    )
    _append_finding(
        findings,
        conn=conn,
        table=_CACHE_TABLE,
        issue_code="TENANT_MISMATCH",
        id_expr="coalesce(t.agency_id::text, 'null') || ':' || t.client_id",
        where_sql=(
            "EXISTS (SELECT 1 FROM clients c "
            "WHERE c.id = t.client_id AND t.agency_id IS DISTINCT FROM c.agency_id)"
        ),
    )


def audit_tenant_integrity(conn: SqlConn) -> TenantIntegrityReport:
    findings: list[TenantIntegrityFinding] = []
    _audit_root_tables(conn, findings)
    _audit_single_parent(conn, findings)
    _audit_dual_parent(conn, findings)
    _audit_artifacts(conn, findings)
    _audit_cache(conn, findings)
    findings.sort(key=lambda item: (item.table_name, item.issue_code))
    return TenantIntegrityReport(
        generated_at=_utc_now(),
        ok=not findings,
        findings=findings,
    )


def _agency_count(conn: SqlConn) -> int:
    row = _fetchone(conn, "SELECT COUNT(*) AS total FROM accounts_agency")
    return int((row or {}).get("total") or 0)


def _sole_agency_id(conn: SqlConn) -> int | None:
    row = _fetchone(conn, "SELECT id FROM accounts_agency ORDER BY id LIMIT 1")
    value = (row or {}).get("id")
    return int(value) if value is not None else None


def repair_tenant_integrity(conn: SqlConn) -> TenantIntegrityReport:
    agency_count = _agency_count(conn)
    sole_agency_id = _sole_agency_id(conn) if agency_count == 1 else None

    if sole_agency_id is not None:
        for table in _ROOT_TABLES:
            _rowcount(
                conn,
                f"UPDATE {table} SET agency_id = %s WHERE agency_id IS NULL",
                (sole_agency_id,),
            )

    for table, _, parent_id_col, parent_table in _SINGLE_PARENT_TABLES:
        _rowcount(
            conn,
            f"""
            UPDATE {table} t
            SET agency_id = p.agency_id
            FROM {parent_table} p
            WHERE p.id = t.{parent_id_col}
              AND t.agency_id IS DISTINCT FROM p.agency_id
            """,
        )

    for table, _ in _DUAL_PARENT_TABLES:
        _rowcount(
            conn,
            f"""
            UPDATE {table} t
            SET agency_id = c.agency_id
            FROM clients c
            , listings l
            WHERE c.id = t.client_id
              AND l.id = t.listing_id
              AND c.agency_id = l.agency_id
              AND t.agency_id IS DISTINCT FROM c.agency_id
            """,
        )

    for table in _ARTIFACT_TABLES:
        _rowcount(
            conn,
            f"""
            UPDATE {table} t
            SET agency_id = d.agency_id
            FROM demandes d
            , offers o
            WHERE d.id = t.demande_id
              AND o.id = t.offer_id
              AND d.agency_id = o.agency_id
              AND t.agency_id IS DISTINCT FROM d.agency_id
            """,
        )
        _rowcount(
            conn,
            f"""
            DELETE FROM {table} t
            WHERE NOT EXISTS (SELECT 1 FROM demandes d WHERE d.id = t.demande_id)
               OR NOT EXISTS (SELECT 1 FROM offers o WHERE o.id = t.offer_id)
               OR EXISTS (
                   SELECT 1
                   FROM demandes d
                   JOIN offers o ON o.id = t.offer_id
                   WHERE d.id = t.demande_id
                     AND d.agency_id IS DISTINCT FROM o.agency_id
               )
            """,
        )

    _rowcount(
        conn,
        f"""
        UPDATE {_CACHE_TABLE} m
        SET agency_id = c.agency_id
        FROM clients c
        WHERE c.id = m.client_id
          AND m.agency_id IS DISTINCT FROM c.agency_id
        """,
    )
    _rowcount(
        conn,
        f"""
        DELETE FROM {_CACHE_TABLE} m
        WHERE NOT EXISTS (
            SELECT 1 FROM clients c WHERE c.id = m.client_id
        )
        """,
    )

    return audit_tenant_integrity(conn)


def report_summary(report: TenantIntegrityReport) -> str:
    if report.ok:
        return "tenant_fk_integrity: OK"
    lines = ["tenant_fk_integrity: issues found"]
    for finding in report.findings:
        sample = ", ".join(finding.sample_ids) if finding.sample_ids else "-"
        lines.append(
            f"- {finding.table_name} {finding.issue_code}: rows={finding.row_count} sample={sample}"
        )
    return "\n".join(lines)


def assert_report_ok(report: TenantIntegrityReport) -> None:
    if report.ok:
        return
    raise RuntimeError(report_summary(report))


__all__ = [
    "TenantIntegrityFinding",
    "TenantIntegrityReport",
    "assert_report_ok",
    "audit_tenant_integrity",
    "repair_tenant_integrity",
    "report_summary",
]
