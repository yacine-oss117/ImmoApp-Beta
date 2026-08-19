from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django

    django.setup()


@dataclass(frozen=True)
class SeedUser:
    username: str
    password: str
    role: str
    agency_id: int | None
    is_superuser: bool


@dataclass(frozen=True)
class SeedPayload:
    tag: str
    tenants: int
    rows_per_tenant: int
    seeded_at_utc: str
    superuser: SeedUser
    owners: list[SeedUser]
    managers: list[SeedUser]
    agents: list[SeedUser]


def _seed_superuser(
    session: Any,
    *,
    tag: str,
    password_hash: str,
    password_plain: str,
) -> SeedUser:
    username = f"perf_super_{tag}"
    email = f"{username}@perf.local"
    row = session.execute(
        """
        INSERT INTO accounts_user (
            password, last_login, is_superuser, username, first_name, last_name, email,
            is_staff, is_active, date_joined,
            role, agency_id, manager_id, access_scope, is_owner, can_hard_delete,
            can_import, import_granted_by_id, timezone, locale,
            first_name_enc, last_name_enc, first_name_search_src, last_name_search_src,
            mfa_totp_secret, mfa_totp_secret_enc
        )
        VALUES (
            %s, NULL, true, %s, 'Perf', 'Superuser', %s,
            true, true, CURRENT_TIMESTAMP,
            'super_admin', NULL, NULL, 'agency', false, true,
            false, NULL, 'UTC', 'en',
            '', '', 'Perf', 'Superuser',
            '', ''
        )
        ON CONFLICT (username) DO UPDATE SET
            password = EXCLUDED.password,
            email = EXCLUDED.email,
            is_superuser = true,
            is_staff = true,
            is_active = true,
            role = 'super_admin',
            agency_id = NULL,
            manager_id = NULL,
            access_scope = 'agency',
            is_owner = false,
            can_hard_delete = true,
            can_import = false,
            import_granted_by_id = NULL,
            timezone = 'UTC',
            locale = 'en'
        RETURNING id
        """,
        (password_hash, username, email),
    ).fetchone()
    if row is None:
        raise RuntimeError("Failed to create perf superuser.")
    return SeedUser(
        username=username,
        password=password_plain,
        role="super_admin",
        agency_id=None,
        is_superuser=True,
    )


def _seed_agency(session: Any, *, tag: str, tenant_index: int) -> int:
    code = f"PERF_{tag}_{tenant_index:04d}"
    label = f"Perf Agency {tag} {tenant_index:04d}"
    row = session.execute(
        """
        INSERT INTO accounts_agency (
            legal_name, display_name, agency_code,
            kbis_number, phone_number, phone_number_enc, email,
            address_line1, address_line1_enc, address_line2, address_line2_enc,
            city, city_enc, postal_code, country,
            is_active, max_users, max_managers, max_agents_per_manager,
            created_at, updated_at
        )
        VALUES (
            %s, %s, %s,
            '', '', '', '',
            '', '', '', '',
            '', '', '', '',
            true, 5000, 500, 500,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (label, label, code),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to create agency for tenant index {tenant_index}.")
    if isinstance(row, dict):
        return int(row["id"])
    return int(row[0])


def _seed_manager_user(
    session: Any,
    *,
    username: str,
    email: str,
    agency_id: int,
    password_hash: str,
    is_owner: bool,
) -> int:
    row = session.execute(
        """
        INSERT INTO accounts_user (
            password, last_login, is_superuser, username, first_name, last_name, email,
            is_staff, is_active, date_joined,
            role, agency_id, manager_id, access_scope, is_owner, can_hard_delete,
            can_import, import_granted_by_id, timezone, locale,
            first_name_enc, last_name_enc, first_name_search_src, last_name_search_src,
            mfa_totp_secret, mfa_totp_secret_enc
        )
        VALUES (
            %s, NULL, false, %s, '', '', %s,
            false, true, CURRENT_TIMESTAMP,
            'manager', %s, NULL, 'agency', %s, false,
            false, NULL, 'UTC', 'en',
            '', '', '', '',
            '', ''
        )
        RETURNING id
        """,
        (password_hash, username, email, agency_id, bool(is_owner)),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to create manager user {username}.")
    if isinstance(row, dict):
        return int(row["id"])
    return int(row[0])


def _seed_agent_user(
    session: Any,
    *,
    username: str,
    email: str,
    agency_id: int,
    manager_id: int,
    password_hash: str,
) -> int:
    row = session.execute(
        """
        INSERT INTO accounts_user (
            password, last_login, is_superuser, username, first_name, last_name, email,
            is_staff, is_active, date_joined,
            role, agency_id, manager_id, access_scope, is_owner, can_hard_delete,
            can_import, import_granted_by_id, timezone, locale,
            first_name_enc, last_name_enc, first_name_search_src, last_name_search_src,
            mfa_totp_secret, mfa_totp_secret_enc
        )
        VALUES (
            %s, NULL, false, %s, '', '', %s,
            false, true, CURRENT_TIMESTAMP,
            'agent', %s, %s, 'own', false, false,
            false, NULL, 'UTC', 'en',
            '', '', '', '',
            '', ''
        )
        RETURNING id
        """,
        (password_hash, username, email, agency_id, manager_id),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to create agent user {username}.")
    if isinstance(row, dict):
        return int(row["id"])
    return int(row[0])


def _seed_business_rows(
    session: Any,
    *,
    agency_id: int,
    rows_per_tenant: int,
    tag: str,
    tenant_index: int,
) -> None:
    marker = f"PERF_{tag}_{tenant_index:04d}"
    location_prefix = f"perf_{tag}_{tenant_index:04d}_loc_"

    session.execute(
        """
        INSERT INTO locations (location_norm)
        SELECT %s || i::text
        FROM generate_series(1, %s) AS i
        ON CONFLICT (location_norm) DO NOTHING
        """,
        (location_prefix, rows_per_tenant),
    )
    session.execute(
        """
        INSERT INTO clients (family_name, phone, status, agency_id, created_at, updated_at)
        SELECT
            %s || '_C_' || i::text,
            '05' || lpad((%s + i)::text, 8, '0'),
            'active',
            %s,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM generate_series(1, %s) AS i
        """,
        (marker, tenant_index * rows_per_tenant, agency_id, rows_per_tenant),
    )
    session.execute(
        """
        INSERT INTO listings (family_name, phone, status, agency_id, created_at, updated_at)
        SELECT
            %s || '_L_' || i::text,
            '06' || lpad((%s + i)::text, 8, '0'),
            'available',
            %s,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM generate_series(1, %s) AS i
        """,
        (marker, tenant_index * rows_per_tenant, agency_id, rows_per_tenant),
    )
    session.execute(
        """
        INSERT INTO demandes (
            client_id, type_id, action_id, wilaya_id,
            beds_min, surface_min, surface_max, budget_min, budget_max,
            floor_min, floor_max, elevator, accessibility_required,
            budget_range, surface_range, beds_range,
            agency_id, created_at, updated_at
        )
        SELECT
            c.id, 1, 1, 1,
            2, 50, 160, 100, 450,
            0, 15, NULL, NULL,
            numrange(100, 450, '[]'),
            numrange(50, 160, '[]'),
            int4range(2, 4, '[]'),
            %s,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM clients c
        WHERE c.agency_id = %s
          AND c.deleted_at IS NULL
        """,
        (agency_id, agency_id),
    )
    session.execute(
        """
        INSERT INTO offers (
            listing_id, type_id, action_id, wilaya_id, location,
            beds, surface, budget, floor, elevator, accessibility_supported,
            price_range,
            agency_id, status, created_at, updated_at
        )
        SELECT
            l.id, 1, 3, 1, %s || row_number() OVER (ORDER BY l.id)::text,
            3, 85, 220, 1, 1, 1,
            numrange(180, 260, '[]'),
            %s, 'available', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM listings l
        WHERE l.agency_id = %s
          AND l.deleted_at IS NULL
        """,
        (location_prefix, agency_id, agency_id),
    )
    session.execute(
        """
        WITH d AS (
            SELECT id, row_number() OVER (ORDER BY id) AS rn
            FROM demandes
            WHERE agency_id = %s
              AND deleted_at IS NULL
        ),
        locs AS (
            SELECT location_id, row_number() OVER (ORDER BY location_id) AS rn
            FROM locations
            WHERE location_norm LIKE %s
            ORDER BY location_id
            LIMIT %s
        )
        INSERT INTO demande_locations (demande_id, location_id, agency_id)
        SELECT d.id, locs.location_id, %s
        FROM d
        JOIN locs ON locs.rn = d.rn
        """,
        (agency_id, f"{location_prefix}%", rows_per_tenant, agency_id),
    )
    session.execute(
        """
        WITH o AS (
            SELECT id, row_number() OVER (ORDER BY id) AS rn
            FROM offers
            WHERE agency_id = %s
              AND deleted_at IS NULL
        ),
        locs AS (
            SELECT location_id, row_number() OVER (ORDER BY location_id) AS rn
            FROM locations
            WHERE location_norm LIKE %s
            ORDER BY location_id
            LIMIT %s
        )
        INSERT INTO offer_locations (offer_id, location_id, agency_id)
        SELECT o.id, locs.location_id, %s
        FROM o
        JOIN locs ON locs.rn = o.rn
        """,
        (agency_id, f"{location_prefix}%", rows_per_tenant, agency_id),
    )
    session.execute(
        """
        INSERT INTO match_counts_cache (client_id, agency_id, count, computed_at, is_dirty)
        SELECT c.id, %s, 0, CURRENT_TIMESTAMP, 1
        FROM clients c
        WHERE c.agency_id = %s
          AND c.deleted_at IS NULL
        ON CONFLICT (client_id) DO UPDATE
        SET agency_id = EXCLUDED.agency_id,
            count = EXCLUDED.count,
            computed_at = EXCLUDED.computed_at,
            is_dirty = EXCLUDED.is_dirty
        """,
        (agency_id, agency_id),
    )


def _safe_delete(session: Any, sql: str, params: tuple[object, ...]) -> None:
    try:
        session.execute(sql, params)
    except Exception:
        return


def _coerce_id(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("Expected integer-like row id value.")
    return int(text)


def _cleanup_import_jobs_for_agencies_and_users(
    session: Any,
    *,
    agency_ids: list[int],
    usernames: list[str],
) -> None:
    if agency_ids:
        _safe_delete(
            session,
            "DELETE FROM imports_importrowaudit WHERE agency_id = ANY(%s)",
            (agency_ids,),
        )
        _safe_delete(
            session,
            "DELETE FROM imports_importjob WHERE agency_id = ANY(%s)",
            (agency_ids,),
        )
    for username in usernames:
        _safe_delete(
            session,
            "DELETE FROM imports_importrowaudit WHERE actor_id IN "
            "(SELECT id FROM accounts_user WHERE username = %s)",
            (username,),
        )
        _safe_delete(
            session,
            "DELETE FROM imports_importjob WHERE user_id IN "
            "(SELECT id FROM accounts_user WHERE username = %s)",
            (username,),
        )


def _cleanup_tag(tag: str) -> dict[str, int]:
    from server.pg.uow import admin_transaction

    cleaned_agencies = 0
    cleaned_users = 0

    with admin_transaction() as session:
        rows = session.execute(
            "SELECT id FROM accounts_agency WHERE agency_code LIKE %s",
            (f"PERF_{tag}_%",),
        ).fetchall()
        agency_ids: list[int] = []
        for row in rows:
            raw_id = row["id"] if isinstance(row, dict) else row[0]
            agency_ids.append(_coerce_id(raw_id))

        if agency_ids:
            user_rows = session.execute(
                "SELECT id FROM accounts_user WHERE agency_id = ANY(%s)",
                (agency_ids,),
            ).fetchall()
            user_ids: list[int] = []
            for row in user_rows:
                raw_id = row["id"] if isinstance(row, dict) else row[0]
                user_ids.append(_coerce_id(raw_id))
            cleaned_users = len(user_ids)

            _cleanup_import_jobs_for_agencies_and_users(
                session,
                agency_ids=agency_ids,
                usernames=[],
            )

            _safe_delete(
                session,
                "DELETE FROM token_blacklist_blacklistedtoken "
                "WHERE token_id IN (SELECT id FROM token_blacklist_outstandingtoken WHERE user_id = ANY(%s))",
                (user_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = ANY(%s)",
                (user_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM auth_security_events WHERE user_id = ANY(%s)",
                (user_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM notifications WHERE user_id = ANY(%s)",
                (user_ids,),
            )

            _safe_delete(
                session,
                "DELETE FROM api_rebuild_job_leases WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM tenant_work_lease WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM match_rebuild_state WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM match_pairs WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM match_candidates WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM match_counts_cache WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM demande_locations WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM offer_locations WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(session, "DELETE FROM demandes WHERE agency_id = ANY(%s)", (agency_ids,))
            _safe_delete(session, "DELETE FROM offers WHERE agency_id = ANY(%s)", (agency_ids,))
            _safe_delete(session, "DELETE FROM clients WHERE agency_id = ANY(%s)", (agency_ids,))
            _safe_delete(session, "DELETE FROM listings WHERE agency_id = ANY(%s)", (agency_ids,))
            _safe_delete(
                session,
                "DELETE FROM auth_security_events WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM accounts_user WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM accounts_agency WHERE id = ANY(%s)",
                (agency_ids,),
            )
            cleaned_agencies = len(agency_ids)

        perf_super_username = f"perf_super_{tag}"
        _cleanup_import_jobs_for_agencies_and_users(
            session,
            agency_ids=[],
            usernames=[perf_super_username],
        )
        _safe_delete(
            session,
            "DELETE FROM token_blacklist_blacklistedtoken "
            "WHERE token_id IN (SELECT id FROM token_blacklist_outstandingtoken WHERE user_id IN "
            "(SELECT id FROM accounts_user WHERE username = %s))",
            (perf_super_username,),
        )
        _safe_delete(
            session,
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id IN "
            "(SELECT id FROM accounts_user WHERE username = %s)",
            (perf_super_username,),
        )
        _safe_delete(
            session, "DELETE FROM accounts_user WHERE username = %s", (perf_super_username,)
        )
        _safe_delete(
            session,
            "DELETE FROM locations WHERE location_norm LIKE %s "
            "AND NOT EXISTS (SELECT 1 FROM demande_locations dl WHERE dl.location_id = locations.location_id) "
            "AND NOT EXISTS (SELECT 1 FROM offer_locations ol WHERE ol.location_id = locations.location_id)",
            (f"perf_{tag}_%",),
        )

    return {"agencies": cleaned_agencies, "users": cleaned_users}


def _cleanup_all_perf_data() -> dict[str, int]:
    from server.pg.uow import admin_transaction

    cleaned_agencies = 0
    cleaned_users = 0

    with admin_transaction() as session:
        rows = session.execute(
            "SELECT id FROM accounts_agency WHERE agency_code LIKE %s",
            ("PERF_%",),
        ).fetchall()
        agency_ids: list[int] = []
        for row in rows:
            raw_id = row["id"] if isinstance(row, dict) else row[0]
            agency_ids.append(_coerce_id(raw_id))

        if agency_ids:
            user_rows = session.execute(
                "SELECT id FROM accounts_user WHERE agency_id = ANY(%s)",
                (agency_ids,),
            ).fetchall()
            user_ids: list[int] = []
            for row in user_rows:
                raw_id = row["id"] if isinstance(row, dict) else row[0]
                user_ids.append(_coerce_id(raw_id))
            cleaned_users = len(user_ids)

            _cleanup_import_jobs_for_agencies_and_users(
                session,
                agency_ids=agency_ids,
                usernames=[],
            )

            _safe_delete(
                session,
                "DELETE FROM token_blacklist_blacklistedtoken "
                "WHERE token_id IN (SELECT id FROM token_blacklist_outstandingtoken WHERE user_id = ANY(%s))",
                (user_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = ANY(%s)",
                (user_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM auth_security_events WHERE user_id = ANY(%s)",
                (user_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM notifications WHERE user_id = ANY(%s)",
                (user_ids,),
            )

            _safe_delete(
                session,
                "DELETE FROM api_rebuild_job_leases WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM tenant_work_lease WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM match_rebuild_state WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM match_pairs WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM match_candidates WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM match_counts_cache WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM demande_locations WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM offer_locations WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(session, "DELETE FROM demandes WHERE agency_id = ANY(%s)", (agency_ids,))
            _safe_delete(session, "DELETE FROM offers WHERE agency_id = ANY(%s)", (agency_ids,))
            _safe_delete(session, "DELETE FROM clients WHERE agency_id = ANY(%s)", (agency_ids,))
            _safe_delete(session, "DELETE FROM listings WHERE agency_id = ANY(%s)", (agency_ids,))
            _safe_delete(
                session,
                "DELETE FROM auth_security_events WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM accounts_user WHERE agency_id = ANY(%s)",
                (agency_ids,),
            )
            _safe_delete(
                session,
                "DELETE FROM accounts_agency WHERE id = ANY(%s)",
                (agency_ids,),
            )
            cleaned_agencies = len(agency_ids)

        _safe_delete(
            session,
            "DELETE FROM imports_importrowaudit WHERE actor_id IN "
            "(SELECT id FROM accounts_user WHERE username LIKE %s)",
            ("perf_%",),
        )
        _safe_delete(
            session,
            "DELETE FROM imports_importjob WHERE user_id IN "
            "(SELECT id FROM accounts_user WHERE username LIKE %s)",
            ("perf_%",),
        )
        _safe_delete(
            session,
            "DELETE FROM token_blacklist_blacklistedtoken "
            "WHERE token_id IN (SELECT id FROM token_blacklist_outstandingtoken WHERE user_id IN "
            "(SELECT id FROM accounts_user WHERE username LIKE %s))",
            ("perf_%",),
        )
        _safe_delete(
            session,
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id IN "
            "(SELECT id FROM accounts_user WHERE username LIKE %s)",
            ("perf_%",),
        )
        _safe_delete(
            session,
            "DELETE FROM accounts_user WHERE username LIKE %s",
            ("perf_%",),
        )
        _safe_delete(
            session,
            "DELETE FROM locations WHERE location_norm LIKE %s "
            "AND NOT EXISTS (SELECT 1 FROM demande_locations dl WHERE dl.location_id = locations.location_id) "
            "AND NOT EXISTS (SELECT 1 FROM offer_locations ol WHERE ol.location_id = locations.location_id)",
            ("perf_%",),
        )

    return {"agencies": cleaned_agencies, "users": cleaned_users}


def _build_payload(
    *,
    tag: str,
    tenants: int,
    rows_per_tenant: int,
    superuser: SeedUser,
    owners: list[SeedUser],
    managers: list[SeedUser],
    agents: list[SeedUser],
) -> SeedPayload:
    return SeedPayload(
        tag=tag,
        tenants=tenants,
        rows_per_tenant=rows_per_tenant,
        seeded_at_utc=datetime.now(tz=timezone.utc).isoformat(),
        superuser=superuser,
        owners=owners,
        managers=managers,
        agents=agents,
    )


def _vacuum_analyze_perf_tables() -> None:
    from django.db import connection

    tables = (
        "accounts_agency",
        "accounts_user",
        "clients",
        "listings",
        "demandes",
        "offers",
        "demande_locations",
        "offer_locations",
        "notifications",
        "api_rebuild_job_leases",
        "match_counts_cache",
        "locations",
    )
    previous_autocommit = connection.get_autocommit()
    try:
        connection.set_autocommit(True)
        with connection.cursor() as cursor:
            for table_name in tables:
                cursor.execute(f"VACUUM (ANALYZE) {table_name}")
    finally:
        connection.set_autocommit(previous_autocommit)


def _write_payload(payload: SeedPayload, output_file: str | None) -> None:
    rendered = json.dumps(
        {
            "tag": payload.tag,
            "tenants": payload.tenants,
            "rows_per_tenant": payload.rows_per_tenant,
            "seeded_at_utc": payload.seeded_at_utc,
            "superuser": asdict(payload.superuser),
            "owners": [asdict(item) for item in payload.owners],
            "managers": [asdict(item) for item in payload.managers],
            "agents": [asdict(item) for item in payload.agents],
        },
        indent=2,
    )
    if output_file:
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


def _seed(args: argparse.Namespace) -> SeedPayload:
    from django.contrib.auth.hashers import make_password
    from server.pg.uow import admin_transaction

    tag = str(args.tag)
    tenants = int(args.tenants)
    rows_per_tenant = int(args.rows_per_tenant)
    owner_password = str(args.owner_password)
    manager_password = str(args.manager_password)
    agent_password = str(args.agent_password)
    super_password = str(args.superuser_password)

    if tenants <= 0:
        raise ValueError("tenants must be > 0")
    if rows_per_tenant <= 0:
        raise ValueError("rows_per_tenant must be > 0")

    _cleanup_tag(tag)

    owners: list[SeedUser] = []
    managers: list[SeedUser] = []
    agents: list[SeedUser] = []

    owner_hash = make_password(owner_password)
    manager_hash = make_password(manager_password)
    agent_hash = make_password(agent_password)
    super_hash = make_password(super_password)

    with admin_transaction() as session:
        superuser = _seed_superuser(
            session,
            tag=tag,
            password_hash=super_hash,
            password_plain=super_password,
        )

        for tenant_index in range(1, tenants + 1):
            agency_id = _seed_agency(session, tag=tag, tenant_index=tenant_index)

            owner_username = f"perf_owner_{tag}_{tenant_index:04d}"
            owner_email = f"{owner_username}@perf.local"
            _seed_manager_user(
                session,
                username=owner_username,
                email=owner_email,
                agency_id=agency_id,
                password_hash=owner_hash,
                is_owner=True,
            )
            owners.append(
                SeedUser(
                    username=owner_username,
                    password=owner_password,
                    role="manager_owner",
                    agency_id=agency_id,
                    is_superuser=False,
                )
            )

            manager_username = f"perf_mgr_{tag}_{tenant_index:04d}"
            manager_email = f"{manager_username}@perf.local"
            manager_id = _seed_manager_user(
                session,
                username=manager_username,
                email=manager_email,
                agency_id=agency_id,
                password_hash=manager_hash,
                is_owner=False,
            )
            managers.append(
                SeedUser(
                    username=manager_username,
                    password=manager_password,
                    role="manager",
                    agency_id=agency_id,
                    is_superuser=False,
                )
            )

            agent_username = f"perf_agent_{tag}_{tenant_index:04d}"
            agent_email = f"{agent_username}@perf.local"
            _seed_agent_user(
                session,
                username=agent_username,
                email=agent_email,
                agency_id=agency_id,
                manager_id=manager_id,
                password_hash=agent_hash,
            )
            agents.append(
                SeedUser(
                    username=agent_username,
                    password=agent_password,
                    role="agent",
                    agency_id=agency_id,
                    is_superuser=False,
                )
            )

            _seed_business_rows(
                session,
                agency_id=agency_id,
                rows_per_tenant=rows_per_tenant,
                tag=tag,
                tenant_index=tenant_index,
            )

    _vacuum_analyze_perf_tables()

    return _build_payload(
        tag=tag,
        tenants=tenants,
        rows_per_tenant=rows_per_tenant,
        superuser=superuser,
        owners=owners,
        managers=managers,
        agents=agents,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed deterministic multi-tenant data for performance load testing.",
    )
    parser.add_argument("--tag", default=datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S"))
    parser.add_argument("--tenants", type=int, default=20)
    parser.add_argument("--rows-per-tenant", type=int, default=400)
    parser.add_argument("--owner-password", default="PerfOwnerPass_123!")
    parser.add_argument("--manager-password", default="PerfManagerPass_123!")
    parser.add_argument("--agent-password", default="PerfAgentPass_123!")
    parser.add_argument("--superuser-password", default="PerfSuperPass_123!")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--cleanup-all", action="store_true")
    return parser.parse_args()


def main() -> None:
    _bootstrap()
    args = _parse_args()

    if bool(args.cleanup):
        result = _cleanup_tag(str(args.tag))
        print(
            json.dumps(
                {
                    "tag": str(args.tag),
                    "cleanup": True,
                    "deleted_agencies": result["agencies"],
                    "deleted_users": result["users"],
                },
                indent=2,
            )
        )
        return

    if bool(args.cleanup_all):
        result = _cleanup_all_perf_data()
        print(
            json.dumps(
                {
                    "cleanup_all": True,
                    "deleted_agencies": result["agencies"],
                    "deleted_users": result["users"],
                },
                indent=2,
            )
        )
        return

    payload = _seed(args)
    _write_payload(payload, str(args.output_file) if args.output_file else None)


if __name__ == "__main__":
    main()
