from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.env_flags import EnvBoolError, parse_bool_env_value

BOOLEAN_TRUE_CASES = ("1", "true", "yes", "on", " TRUE ")
BOOLEAN_FALSE_CASES = (None, "", "0", "false", "no", "off", " OFF ")


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    os.environ.setdefault("IMMOAPP_SKIP_CELERY_APP", "1")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _create_agency():
    from server.accounts.models import Agency

    suffix = uuid.uuid4().hex[:8]
    return Agency.objects.create(
        legal_name=f"Agency {suffix}",
        display_name=f"Agency {suffix}",
        agency_code=f"SESS{suffix}",
    )


def _unique_email(seed: str) -> str:
    local, _, domain = seed.partition("@")
    resolved_domain = domain or "example.com"
    return f"{local}-{uuid.uuid4().hex[:8]}@{resolved_domain}"


def _create_manager(*, agency, email: str, owner: bool):
    User = get_user_model()
    unique_email = _unique_email(email)
    user = User(
        username=unique_email,
        email=unique_email,
        role="manager",
        agency=agency,
        manager=None,
        is_owner=owner,
        is_active=True,
    )
    user.set_password("StrongPassword!123")
    user.save(validate=False)
    return user


def test_validate_token_session_rejects_revoked_session() -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner@example.com", owner=True)
    session = auth_sessions.issue_session(user=user, source_ip="10.0.0.1", user_agent="ua")

    auth_sessions.revoke_session(actor=user, session_id=session.session_id)
    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=timezone.now().timestamp(),
    )

    assert ok is False
    assert reason == "session_revoked"


def test_validate_token_session_cache_does_not_outlive_actual_expiry(monkeypatch) -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-cache@example.com", owner=True)
    session = auth_sessions.issue_session(user=user, source_ip="10.0.0.10", user_agent="ua")
    base_now = timezone.now()
    session.expires_at = base_now + timedelta(seconds=1)
    session.save(update_fields=["expires_at"])

    monkeypatch.setattr(
        auth_sessions.session_lifecycle, "_session_validate_cache_seconds", lambda: 60.0
    )
    auth_sessions.session_lifecycle._invalidate_validation_cache()
    monkeypatch.setattr(auth_sessions.session_lifecycle.timezone, "now", lambda: base_now)

    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=base_now.timestamp(),
    )
    assert ok is True
    assert reason is None
    assert (
        int(user.id),
        str(session.session_id),
    ) in auth_sessions.session_lifecycle._SESSION_VALIDATION_CACHE

    monkeypatch.setattr(
        auth_sessions.session_lifecycle.timezone,
        "now",
        lambda: base_now + timedelta(seconds=2),
    )

    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=base_now.timestamp(),
    )

    assert ok is False
    assert reason == "session_expired"

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_validate_token_session_rejects_revoked_session_after_cached_success(monkeypatch) -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-revoke-cache@example.com", owner=True)
    session = auth_sessions.issue_session(user=user, source_ip="10.0.0.11", user_agent="ua")

    monkeypatch.setattr(
        auth_sessions.session_lifecycle, "_session_validate_cache_seconds", lambda: 60.0
    )
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=timezone.now().timestamp(),
    )
    assert ok is True
    assert reason is None

    auth_sessions.revoke_session(actor=user, session_id=session.session_id)
    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=timezone.now().timestamp(),
    )

    assert ok is False
    assert reason == "session_revoked"

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_validate_token_session_rejects_inactive_user_after_cached_success(monkeypatch) -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-inactive-cache@example.com", owner=True)
    session = auth_sessions.issue_session(user=user, source_ip="10.0.0.13", user_agent="ua")

    monkeypatch.setattr(
        auth_sessions.session_lifecycle, "_session_validate_cache_seconds", lambda: 60.0
    )
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    token_iat = timezone.now().timestamp()
    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=token_iat,
    )
    assert ok is True
    assert reason is None
    assert (
        int(user.id),
        str(session.session_id),
    ) in auth_sessions.session_lifecycle._SESSION_VALIDATION_CACHE

    User = get_user_model()
    User.objects.filter(id=user.id).update(is_active=False)

    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=token_iat,
    )

    assert ok is False
    assert reason == "user_inactive"
    assert (
        int(user.id),
        str(session.session_id),
    ) not in auth_sessions.session_lifecycle._SESSION_VALIDATION_CACHE

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_validate_token_session_cache_rechecks_live_db_expiry_changes(monkeypatch) -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-db-expiry@example.com", owner=True)
    session = auth_sessions.issue_session(user=user, source_ip="10.0.0.12", user_agent="ua")

    monkeypatch.setattr(
        auth_sessions.session_lifecycle, "_session_validate_cache_seconds", lambda: 60.0
    )
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=timezone.now().timestamp(),
    )
    assert ok is True
    assert reason is None

    session.expires_at = timezone.now() - timedelta(seconds=1)
    session.save(update_fields=["expires_at"])

    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=timezone.now().timestamp(),
    )

    assert ok is False
    assert reason == "session_expired"

    auth_sessions.session_lifecycle._invalidate_validation_cache()


@pytest.mark.parametrize("raw", BOOLEAN_TRUE_CASES)
def test_env_bool_parser_accepts_truthy_values(raw: str) -> None:
    assert parse_bool_env_value("TEST_FLAG", raw) is True


@pytest.mark.parametrize("raw", BOOLEAN_FALSE_CASES)
def test_env_bool_parser_accepts_falsy_values(raw: str | None) -> None:
    assert parse_bool_env_value("TEST_FLAG", raw) is False


@pytest.mark.parametrize("raw", ("2", "enabled", "maybe"))
def test_env_bool_parser_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(EnvBoolError, match="TEST_FLAG must be a boolean value"):
        parse_bool_env_value("TEST_FLAG", raw)


@pytest.mark.parametrize("raw", BOOLEAN_TRUE_CASES)
def test_validate_token_session_missing_sid_is_rejected_for_truthy_require_sid(
    monkeypatch,
    raw: str,
) -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner2@example.com", owner=True)

    monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", raw)
    assert auth_sessions.validate_token_session(user=user, session_id=None, token_iat=None) == (
        False,
        "missing_session_id",
    )


@pytest.mark.parametrize("raw", BOOLEAN_FALSE_CASES)
def test_validate_token_session_missing_sid_is_allowed_for_falsy_require_sid(
    monkeypatch,
    raw: str | None,
) -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner2@example.com", owner=True)

    if raw is None:
        monkeypatch.delenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", raising=False)
    else:
        monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", raw)
    assert auth_sessions.validate_token_session(user=user, session_id=None, token_iat=None) == (
        True,
        None,
    )


def test_validate_token_session_invalid_require_sid_config_is_rejected(monkeypatch) -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-invalid-sid@example.com", owner=True)
    monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", "enabled")

    with pytest.raises(EnvBoolError, match="IMMOAPP_REQUIRE_SESSION_ID_CLAIM"):
        auth_sessions.validate_token_session(user=user, session_id=None, token_iat=None)


def test_access_token_without_sid_is_rejected_when_sid_required(monkeypatch) -> None:
    _ensure_django()
    import pytest
    from rest_framework.exceptions import AuthenticationFailed
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    from server.api.auth_session_jwt import (
        SessionAwareJWTAuthentication,
        SessionAwareTokenObtainPairSerializer,
    )
    from server.services import auth_sessions

    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "1")
    monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", "1")
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-require-sid@example.com", owner=True)
    refresh = SessionAwareTokenObtainPairSerializer.get_token(user)
    assert refresh.get("sid") is None
    access = str(refresh.access_token)

    factory = APIRequestFactory()
    request = Request(factory.get("/api/v1/users/", HTTP_AUTHORIZATION=f"Bearer {access}"))
    auth = SessionAwareJWTAuthentication()
    with pytest.raises(AuthenticationFailed) as exc_info:
        auth.authenticate(request)

    assert "Session revoked or expired" in str(exc_info.value)

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_revoke_session_preserves_scope_checks() -> None:
    _ensure_django()
    import pytest

    from server.services import auth_sessions

    agency = _create_agency()
    owner = _create_manager(agency=agency, email="owner3@example.com", owner=True)
    other = _create_manager(agency=agency, email="other3@example.com", owner=False)
    session = auth_sessions.issue_session(user=owner, source_ip="10.0.0.2", user_agent="ua")

    with pytest.raises(
        auth_sessions.session_revocation.PermissionDeniedError, match="Forbidden session scope."
    ):
        auth_sessions.revoke_session(actor=other, session_id=session.session_id)


def test_revoke_all_sessions_preserves_except_session_and_list_shape() -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner4@example.com", owner=True)
    keep = auth_sessions.issue_session(user=user, source_ip="10.0.0.3", user_agent="ua")
    revoke = auth_sessions.issue_session(user=user, source_ip="10.0.0.4", user_agent="ub")

    count = auth_sessions.revoke_all_sessions(actor=user, except_session_id=keep.session_id)

    user.refresh_from_db()
    keep.refresh_from_db()
    revoke.refresh_from_db()
    items = auth_sessions.list_user_sessions(user=user)

    assert count == 1
    assert user.session_invalid_before is not None
    assert keep.revoked_at is None
    assert revoke.revoked_at is not None
    assert {
        "session_id",
        "source_ip",
        "user_agent",
        "created_at",
        "last_seen_at",
        "expires_at",
        "revoked_at",
        "revoke_reason",
    }.issubset(items[0].keys())


def test_revoke_user_sessions_invalidates_all_active_sessions_and_cache(monkeypatch) -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-revoke-user@example.com", owner=True)
    first = auth_sessions.issue_session(user=user, source_ip="10.0.0.5", user_agent="ua")
    second = auth_sessions.issue_session(user=user, source_ip="10.0.0.6", user_agent="ub")

    monkeypatch.setattr(
        auth_sessions.session_lifecycle, "_session_validate_cache_seconds", lambda: 60.0
    )
    auth_sessions.session_lifecycle._invalidate_validation_cache()
    token_iat = timezone.now().timestamp()
    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=first.session_id,
        token_iat=token_iat,
    )
    assert ok is True
    assert reason is None

    revoked = auth_sessions.revoke_user_sessions(user=user, reason="user_deactivated")

    user.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert revoked == 2
    assert user.session_invalid_before is not None
    assert first.revoked_at is not None
    assert first.revoke_reason == "user_deactivated"
    assert second.revoked_at is not None
    assert (
        int(user.id),
        str(first.session_id),
    ) not in auth_sessions.session_lifecycle._SESSION_VALIDATION_CACHE

    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=first.session_id,
        token_iat=token_iat,
    )
    assert ok is False
    assert reason in {"session_revoked_before_iat", "session_revoked"}

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_reactivation_does_not_resurrect_old_sessions() -> None:
    _ensure_django()
    from server.services import auth_sessions

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-reactivate@example.com", owner=True)
    session = auth_sessions.issue_session(user=user, source_ip="10.0.0.7", user_agent="ua")
    token_iat = (timezone.now() - timedelta(seconds=10)).timestamp()

    auth_sessions.revoke_user_sessions(user=user, reason="user_deactivated")
    user.is_active = True
    user.save(update_fields=["is_active"])
    user.refresh_from_db()

    ok, reason = auth_sessions.validate_token_session(
        user=user,
        session_id=session.session_id,
        token_iat=token_iat,
    )

    assert ok is False
    assert reason in {"session_revoked_before_iat", "session_revoked"}


def test_deactivate_user_revokes_target_sessions_and_sets_invalid_before() -> None:
    _ensure_django()
    from server.services import auth_sessions, users

    agency = _create_agency()
    owner = _create_manager(agency=agency, email="owner-deactivate@example.com", owner=True)
    target = _create_manager(agency=agency, email="target-deactivate@example.com", owner=False)
    session = auth_sessions.issue_session(user=target, source_ip="10.0.0.8", user_agent="ua")

    users.deactivate_user(actor=owner, user_id=int(target.id))

    target.refresh_from_db()
    session.refresh_from_db()
    assert target.is_active is False
    assert target.session_invalid_before is not None
    assert session.revoked_at is not None
    assert session.revoke_reason == "user_deactivated"


def test_update_user_to_inactive_revokes_target_sessions() -> None:
    _ensure_django()
    from server.services import auth_sessions, users

    agency = _create_agency()
    owner = _create_manager(agency=agency, email="owner-update-inactive@example.com", owner=True)
    target = _create_manager(agency=agency, email="target-update-inactive@example.com", owner=False)
    session = auth_sessions.issue_session(user=target, source_ip="10.0.0.9", user_agent="ua")

    users.update_user(actor=owner, user_id=int(target.id), data={"is_active": False})

    target.refresh_from_db()
    session.refresh_from_db()
    assert target.is_active is False
    assert target.session_invalid_before is not None
    assert session.revoked_at is not None


def _token_blacklist_counts() -> tuple[int, int]:
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    return OutstandingToken.objects.count(), BlacklistedToken.objects.count()


def _issue_refresh_for_user(*, username: str) -> str:
    from server.api.auth_session_jwt import SessionAwareTokenObtainPairSerializer

    pair = SessionAwareTokenObtainPairSerializer().validate(
        {"username": username, "password": "StrongPassword!123"}
    )
    return str(pair["refresh"])


def test_token_obtain_and_refresh_preserve_session_id_claim(monkeypatch) -> None:
    _ensure_django()
    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

    from server.accounts.models import UserSession
    from server.api.auth_session_jwt import (
        SessionAwareTokenObtainPairSerializer,
        SessionAwareTokenRefreshSerializer,
    )
    from server.services import auth_sessions

    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "1")
    monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", "1")
    monkeypatch.setenv("IMMOAPP_MFA_ENFORCE_ROLES", "")
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    agency = _create_agency()
    user = _create_manager(agency=agency, email="owner-login-sid@example.com", owner=True)
    pair = SessionAwareTokenObtainPairSerializer().validate(
        {"username": str(user.username), "password": "StrongPassword!123"}
    )
    refresh = RefreshToken(str(pair["refresh"]))
    access = AccessToken(str(pair["access"]))
    sid = str(refresh.get("sid") or "")
    assert sid
    assert str(access.get("sid") or "") == sid
    session = UserSession.objects.get(session_id=sid)
    assert session.user_id == user.id
    assert session.refresh_jti == str(refresh.get("jti") or "")

    refreshed = SessionAwareTokenRefreshSerializer().validate({"refresh": str(pair["refresh"])})
    rotated_refresh = RefreshToken(str(refreshed["refresh"]))
    rotated_access = AccessToken(str(refreshed["access"]))
    assert str(rotated_refresh.get("sid") or "") == sid
    assert str(rotated_access.get("sid") or "") == sid
    session.refresh_from_db()
    assert session.refresh_jti == str(rotated_refresh.get("jti") or "")

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_deactivated_user_token_is_rejected_on_next_authenticated_request(monkeypatch) -> None:
    _ensure_django()
    import pytest
    from rest_framework.exceptions import AuthenticationFailed
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    from server.api.auth_session_jwt import (
        SessionAwareJWTAuthentication,
        SessionAwareTokenObtainPairSerializer,
    )
    from server.services import auth_sessions, users

    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "1")

    agency = _create_agency()
    owner = _create_manager(agency=agency, email="owner-token-deactivate@example.com", owner=True)
    target = _create_manager(
        agency=agency, email="target-token-deactivate@example.com", owner=False
    )
    session = auth_sessions.issue_session(user=target, source_ip="10.0.0.14", user_agent="ua")
    refresh = SessionAwareTokenObtainPairSerializer.get_token(target)
    refresh["sid"] = str(session.session_id)
    access = str(refresh.access_token)

    factory = APIRequestFactory()
    request = Request(factory.get("/api/v1/users/", HTTP_AUTHORIZATION=f"Bearer {access}"))
    auth = SessionAwareJWTAuthentication()
    assert auth.authenticate(request) is not None

    users.deactivate_user(actor=owner, user_id=int(target.id))

    request_after_deactivate = Request(
        factory.get("/api/v1/users/", HTTP_AUTHORIZATION=f"Bearer {access}")
    )
    with pytest.raises(AuthenticationFailed):
        auth.authenticate(request_after_deactivate)


def test_deactivated_user_refresh_token_is_rejected_when_tracking_disabled(monkeypatch) -> None:
    _ensure_django()
    import pytest
    from rest_framework.exceptions import AuthenticationFailed

    from server.api.auth_session_jwt import SessionAwareTokenRefreshSerializer
    from server.services import auth_sessions, users

    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "0")
    monkeypatch.setenv("IMMOAPP_MFA_ENFORCE_ROLES", "")
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    agency = _create_agency()
    owner = _create_manager(
        agency=agency,
        email="owner-refresh-disabled-deactivate@example.com",
        owner=True,
    )
    target = _create_manager(
        agency=agency,
        email="target-refresh-disabled-deactivate@example.com",
        owner=False,
    )
    refresh = _issue_refresh_for_user(username=str(target.username))
    counts_before = _token_blacklist_counts()

    users.deactivate_user(actor=owner, user_id=int(target.id))

    with pytest.raises(AuthenticationFailed) as exc_info:
        SessionAwareTokenRefreshSerializer().validate({"refresh": refresh})

    message = str(exc_info.value)
    assert "Invalid refresh token" in message
    assert "inactive" not in message.lower()
    assert _token_blacklist_counts() == counts_before

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_deactivated_user_refresh_token_is_rejected_without_rotation(monkeypatch) -> None:
    _ensure_django()
    import pytest
    from rest_framework.exceptions import AuthenticationFailed
    from rest_framework_simplejwt.tokens import RefreshToken

    from server.accounts.models import UserSession
    from server.api.auth_session_jwt import SessionAwareTokenRefreshSerializer
    from server.services import auth_sessions, users

    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "1")
    monkeypatch.setenv("IMMOAPP_MFA_ENFORCE_ROLES", "")
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    agency = _create_agency()
    owner = _create_manager(agency=agency, email="owner-refresh-deactivate@example.com", owner=True)
    target = _create_manager(
        agency=agency,
        email="target-refresh-deactivate@example.com",
        owner=False,
    )

    probe_refresh = _issue_refresh_for_user(username=str(target.username))
    probe_payload = SessionAwareTokenRefreshSerializer().validate({"refresh": probe_refresh})
    assert isinstance(probe_payload.get("access"), str)

    tracked_refresh = _issue_refresh_for_user(username=str(target.username))
    tracked_token = RefreshToken(tracked_refresh)
    tracked_sid = str(tracked_token.get("sid") or "")
    tracked_jti = str(tracked_token.get("jti") or "")
    assert tracked_sid
    assert tracked_jti
    session_before = UserSession.objects.get(session_id=tracked_sid)
    assert session_before.refresh_jti == tracked_jti
    last_seen_before = session_before.last_seen_at
    counts_before = _token_blacklist_counts()

    users.deactivate_user(actor=owner, user_id=int(target.id))

    target.refresh_from_db()
    session = UserSession.objects.get(session_id=tracked_sid)
    assert target.is_active is False
    assert target.session_invalid_before is not None
    assert session.revoked_at is not None
    assert session.revoke_reason == "user_deactivated"

    with pytest.raises(AuthenticationFailed) as exc_info:
        SessionAwareTokenRefreshSerializer().validate({"refresh": tracked_refresh})

    message = str(exc_info.value)
    assert "Invalid refresh token" in message
    assert "inactive" not in message.lower()
    assert _token_blacklist_counts() == counts_before
    session.refresh_from_db()
    assert session.refresh_jti == tracked_jti
    assert session.last_seen_at == last_seen_before

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_revoked_session_refresh_token_is_rejected_before_rotation(monkeypatch) -> None:
    _ensure_django()
    import pytest
    from rest_framework.exceptions import AuthenticationFailed
    from rest_framework_simplejwt.tokens import RefreshToken

    from server.accounts.models import UserSession
    from server.api.auth_session_jwt import SessionAwareTokenRefreshSerializer
    from server.services import auth_sessions

    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "1")
    monkeypatch.setenv("IMMOAPP_MFA_ENFORCE_ROLES", "")
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    agency = _create_agency()
    target = _create_manager(
        agency=agency,
        email="target-refresh-revoked-session@example.com",
        owner=False,
    )

    tracked_refresh = _issue_refresh_for_user(username=str(target.username))
    tracked_token = RefreshToken(tracked_refresh)
    tracked_sid = str(tracked_token.get("sid") or "")
    tracked_jti = str(tracked_token.get("jti") or "")
    assert tracked_sid
    assert tracked_jti
    session_before = UserSession.objects.get(session_id=tracked_sid)
    assert session_before.refresh_jti == tracked_jti
    last_seen_before = session_before.last_seen_at
    counts_before = _token_blacklist_counts()

    revoked = auth_sessions.revoke_user_sessions(user=target, reason="user_deactivated")
    assert revoked == 1

    with pytest.raises(AuthenticationFailed) as exc_info:
        SessionAwareTokenRefreshSerializer().validate({"refresh": tracked_refresh})

    message = str(exc_info.value)
    assert "Session revoked or expired" in message
    assert _token_blacklist_counts() == counts_before
    session = UserSession.objects.get(session_id=tracked_sid)
    assert session.refresh_jti == tracked_jti
    assert session.last_seen_at == last_seen_before
    assert session.revoked_at is not None
    assert session.revoke_reason == "user_deactivated"

    auth_sessions.session_lifecycle._invalidate_validation_cache()


def test_successful_tracked_refresh_rebinds_rotated_refresh_jti(monkeypatch) -> None:
    _ensure_django()
    from rest_framework_simplejwt.tokens import RefreshToken

    from server.accounts.models import UserSession
    from server.api.auth_session_jwt import SessionAwareTokenRefreshSerializer
    from server.services import auth_sessions

    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "1")
    monkeypatch.setenv("IMMOAPP_MFA_ENFORCE_ROLES", "")
    auth_sessions.session_lifecycle._invalidate_validation_cache()

    agency = _create_agency()
    target = _create_manager(
        agency=agency,
        email="target-refresh-success@example.com",
        owner=False,
    )
    refresh = _issue_refresh_for_user(username=str(target.username))
    old_token = RefreshToken(refresh)
    sid = str(old_token.get("sid") or "")
    old_jti = str(old_token.get("jti") or "")
    payload = SessionAwareTokenRefreshSerializer().validate({"refresh": refresh})
    rotated_refresh = str(payload.get("refresh") or "")
    assert rotated_refresh
    new_jti = str(RefreshToken(rotated_refresh).get("jti") or "")
    assert new_jti
    assert new_jti != old_jti
    session = UserSession.objects.get(session_id=sid)
    assert session.refresh_jti == new_jti

    auth_sessions.session_lifecycle._invalidate_validation_cache()
