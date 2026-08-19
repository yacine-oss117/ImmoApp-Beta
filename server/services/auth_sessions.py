"""User session tracking and revocation helpers."""

from __future__ import annotations

from server.accounts.models import UserSession
from server.services import session_lifecycle, session_revocation


def issue_session(
    *,
    user: object,
    source_ip: str | None,
    user_agent: str | None,
) -> UserSession:
    return session_lifecycle.issue_session_impl(
        user=user,
        source_ip=source_ip,
        user_agent=user_agent,
    )


def bind_refresh_jti(*, session_id: object, refresh_jti: str | None) -> None:
    session_lifecycle.bind_refresh_jti_impl(session_id=session_id, refresh_jti=refresh_jti)


def touch_session(*, session_id: object) -> None:
    session_lifecycle.touch_session_impl(session_id=session_id)


def list_user_sessions(*, user: object) -> list[dict[str, object]]:
    return session_revocation.list_user_sessions_impl(user=user)


def revoke_session(*, actor: object, session_id: object, reason: str = "user_revoke") -> None:
    session_revocation.revoke_session_impl(actor=actor, session_id=session_id, reason=reason)


def revoke_all_sessions(*, actor: object, except_session_id: object | None = None) -> int:
    return session_revocation.revoke_all_sessions_impl(
        actor=actor,
        except_session_id=except_session_id,
    )


def revoke_user_sessions(*, user: object, reason: str = "user_deactivated") -> int:
    return session_revocation.revoke_user_sessions_impl(user=user, reason=reason)


def validate_token_session(
    *,
    user: object,
    session_id: object,
    token_iat: object,
) -> tuple[bool, str | None]:
    return session_lifecycle.validate_token_session_impl(
        user=user,
        session_id=session_id,
        token_iat=token_iat,
    )


__all__ = [
    "bind_refresh_jti",
    "issue_session",
    "list_user_sessions",
    "revoke_all_sessions",
    "revoke_session",
    "revoke_user_sessions",
    "validate_token_session",
]
