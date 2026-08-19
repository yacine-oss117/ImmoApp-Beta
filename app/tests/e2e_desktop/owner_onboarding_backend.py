from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.tests.e2e_desktop.backend import DesktopUser, cleanup_desktop_user
from app.tests.server_tests._integration_auth_helpers import admin_conn


@dataclass(frozen=True)
class EmailOutboxRow:
    id: str
    to_email: str
    subject: str
    body_text: str


def suspend_active_hub_owners_and_admins() -> list[tuple[int, bool]]:
    """Temporarily disable active Hub-authorized users for first-owner E2E."""

    conn = admin_conn()
    try:
        rows = conn.execute("""
            SELECT id, is_active
            FROM accounts_user
            WHERE is_active = TRUE
              AND (
                    is_superuser = TRUE
                 OR (role = 'manager' AND is_owner = TRUE)
                 OR (role = 'manager' AND can_hard_delete = TRUE)
              )
            ORDER BY id
            """).fetchall()
        snapshot = [(int(row["id"]), bool(row["is_active"])) for row in rows]
        if snapshot:
            conn.execute(
                "UPDATE accounts_user SET is_active = FALSE WHERE id = ANY(%s)",
                ([user_id for user_id, _is_active in snapshot],),
            )
        conn.commit()
        return snapshot
    finally:
        conn.close()


def restore_hub_owner_admin_activity(snapshot: list[tuple[int, bool]]) -> None:
    if not snapshot:
        return
    conn = admin_conn()
    try:
        for user_id, is_active in snapshot:
            conn.execute(
                "UPDATE accounts_user SET is_active = %s WHERE id = %s",
                (is_active, user_id),
            )
        conn.commit()
    finally:
        conn.close()


def registration_request_by_email(owner_email: str) -> dict[str, Any] | None:
    conn = admin_conn()
    try:
        row = conn.execute(
            """
            SELECT id::text AS id, owner_email, status, reviewed_at, created_at
            FROM accounts_registrationrequest
            WHERE lower(owner_email) = lower(%s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(owner_email),),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def user_by_email(email: str) -> dict[str, Any] | None:
    conn = admin_conn()
    try:
        row = conn.execute(
            """
            SELECT id, agency_id, username, email, role, is_owner, is_active
            FROM accounts_user
            WHERE lower(email) = lower(%s) OR lower(username) = lower(%s)
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(email), str(email)),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def wait_for_registration_request(
    owner_email: str,
    *,
    status: str | None = None,
    timeout: float = 45.0,
    interval: float = 0.5,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = registration_request_by_email(owner_email)
        if row is not None and (status is None or str(row.get("status") or "") == status):
            return row
        time.sleep(interval)
    expected = f" with status {status!r}" if status else ""
    raise AssertionError(f"Registration request for {owner_email!r}{expected} did not appear")


def latest_email_outbox(
    *,
    to_email: str,
    subject_contains: str = "",
    body_contains: str = "",
) -> EmailOutboxRow | None:
    conn = admin_conn()
    try:
        clauses = ["lower(to_email) = lower(%s)"]
        params: list[object] = [str(to_email)]
        if subject_contains:
            clauses.append("subject ILIKE %s")
            params.append(f"%{subject_contains}%")
        if body_contains:
            clauses.append("body_text ILIKE %s")
            params.append(f"%{body_contains}%")
        row = conn.execute(
            f"""
            SELECT id::text AS id, to_email, subject, body_text
            FROM accounts_emailoutbox
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        return EmailOutboxRow(
            id=str(row["id"]),
            to_email=str(row["to_email"]),
            subject=str(row["subject"]),
            body_text=str(row["body_text"]),
        )
    finally:
        conn.close()


def wait_for_email_outbox(
    *,
    to_email: str,
    subject_contains: str = "",
    body_contains: str = "",
    timeout: float = 45.0,
    interval: float = 0.5,
) -> EmailOutboxRow:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = latest_email_outbox(
            to_email=to_email,
            subject_contains=subject_contains,
            body_contains=body_contains,
        )
        if row is not None:
            return row
        time.sleep(interval)
    raise AssertionError(
        "Email outbox row did not appear: "
        f"to={to_email!r} subject_contains={subject_contains!r} body_contains={body_contains!r}"
    )


def cleanup_owner_registration_email(
    owner_email: str,
    *,
    platform_admin_email: str = "",
) -> None:
    normalized_email = str(owner_email).strip().lower()
    if not normalized_email:
        return

    conn = admin_conn()
    try:
        user_row = conn.execute(
            """
            SELECT id, agency_id, username
            FROM accounts_user
            WHERE lower(email) = lower(%s) OR lower(username) = lower(%s)
            ORDER BY id DESC
            LIMIT 1
            """,
            (normalized_email, normalized_email),
        ).fetchone()
    finally:
        conn.close()

    if user_row is not None and user_row.get("agency_id") is not None:
        cleanup_desktop_user(
            DesktopUser(
                agency_id=int(user_row["agency_id"]),
                user_id=int(user_row["id"]),
                username=str(user_row.get("username") or normalized_email),
                password="",
            )
        )

    conn = admin_conn()
    try:
        owner_pattern = f"%{normalized_email}%"
        conn.execute(
            """
            DELETE FROM accounts_emailoutbox
            WHERE lower(to_email) = lower(%s)
               OR body_text ILIKE %s
               OR body_html ILIKE %s
            """,
            (normalized_email, owner_pattern, owner_pattern),
        )
        if platform_admin_email:
            conn.execute(
                """
                DELETE FROM accounts_emailoutbox
                WHERE lower(to_email) = lower(%s)
                  AND (body_text ILIKE %s OR body_html ILIKE %s)
                """,
                (str(platform_admin_email), owner_pattern, owner_pattern),
            )
        conn.execute(
            "DELETE FROM accounts_registrationrequest WHERE lower(owner_email) = lower(%s)",
            (normalized_email,),
        )
        conn.commit()
    finally:
        conn.close()
