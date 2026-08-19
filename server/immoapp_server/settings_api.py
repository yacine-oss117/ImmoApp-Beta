"""
API and framework settings.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta

_DEFAULT_AUTH_CLASS = "server.api.auth_session_jwt.SessionAwareJWTAuthentication"

REST_FRAMEWORK: dict[str, object] = {
    "DEFAULT_AUTHENTICATION_CLASSES": (_DEFAULT_AUTH_CLASS,),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "server.api.exception_handler.global_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "server.api.throttling.HeaderAnonRateThrottle",
        "server.api.throttling.HeaderAgencyRateThrottle",
        "server.api.throttling.HeaderUserRateThrottle",
        "server.api.throttling.HeaderScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "agency": os.environ.get("AGENCY_THROTTLE", "30000/hour"),
        "user": os.environ.get("USER_THROTTLE", "20000/hour"),
        "simulation": "5/hour",
        "sync": os.environ.get("SYNC_THROTTLE", "60/minute"),
        "users_scope_all": os.environ.get("USERS_SCOPE_ALL_THROTTLE", "10/minute"),
        "match_cache_all": os.environ.get("MATCH_CACHE_ALL_THROTTLE", "10/minute"),
        "cache_rebuild": os.environ.get("CACHE_REBUILD_THROTTLE", "30/hour"),
        "token_obtain": os.environ.get("TOKEN_OBTAIN_THROTTLE", "20/minute"),
        "token_refresh": os.environ.get("TOKEN_REFRESH_THROTTLE", "10/minute"),
        "token_oidc": os.environ.get("TOKEN_OIDC_THROTTLE", "20/minute"),
        "password_forgot": os.environ.get("PASSWORD_FORGOT_THROTTLE", "10/minute"),
        "password_reset": os.environ.get("PASSWORD_RESET_THROTTLE", "10/minute"),
        "account_activate": os.environ.get("ACCOUNT_ACTIVATE_THROTTLE", "10/minute"),
        "register": os.environ.get("REGISTER_THROTTLE", "3/hour"),
        "activate": os.environ.get("ACTIVATE_THROTTLE", "5/hour"),
        "accept_invite": os.environ.get("ACCEPT_INVITE_THROTTLE", "5/hour"),
        "invite_resend": os.environ.get("INVITE_RESEND_THROTTLE", "10/hour"),
        "step_up_auth": os.environ.get("STEP_UP_AUTH_THROTTLE", "20/hour"),
        "mfa_totp": os.environ.get("MFA_TOTP_THROTTLE", "30/hour"),
        "auth_sessions": os.environ.get("AUTH_SESSIONS_THROTTLE", "60/hour"),
        "hub_manager_owner_state": os.environ.get("HUB_MANAGER_OWNER_STATE_THROTTLE", "60/minute"),
        "hub_manager_authorization": os.environ.get(
            "HUB_MANAGER_AUTHORIZATION_THROTTLE", "20/minute"
        ),
        "hub_manager_authorization_consume": os.environ.get(
            "HUB_MANAGER_AUTHORIZATION_CONSUME_THROTTLE", "30/minute"
        ),
        "privilege_elevation": os.environ.get("PRIVILEGE_ELEVATION_THROTTLE", "40/hour"),
        "compliance_export": os.environ.get("COMPLIANCE_EXPORT_THROTTLE", "1/hour"),
        "compliance_delete": os.environ.get("COMPLIANCE_DELETE_THROTTLE", "1/hour"),
    },
}

DEFAULT_IMPORT_BATCH_SIZE = int(os.environ.get("IMPORT_BATCH_SIZE", "500"))

SPECTACULAR_SETTINGS = {
    "TITLE": "ImmoApp API",
    "DESCRIPTION": "API schema for ImmoApp.",
    "VERSION": "v1",
}

API_DEPRECATION_POLICIES: list[dict[str, object]] = []
_deprecation_raw = os.environ.get("API_DEPRECATION_POLICIES", "").strip()
if _deprecation_raw:
    try:
        policies = json.loads(_deprecation_raw)
        if isinstance(policies, list):
            API_DEPRECATION_POLICIES = [
                policy
                for policy in policies
                if isinstance(policy, dict) and policy.get("path_prefix")
            ]
    except json.JSONDecodeError:
        API_DEPRECATION_POLICIES = []

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "15"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", "1"))),
    "ROTATE_REFRESH_TOKENS": os.environ.get("JWT_ROTATE_REFRESH_TOKENS", "1") == "1",
    "BLACKLIST_AFTER_ROTATION": os.environ.get("JWT_BLACKLIST_AFTER_ROTATION", "1") == "1",
}

cors_origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]
CORS_ALLOW_CREDENTIALS = os.environ.get("CORS_ALLOW_CREDENTIALS", "0") == "1"

CSP_HEADER = os.environ.get(
    "CSP_HEADER",
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self' data:; connect-src 'self'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
)

__all__ = [
    "API_DEPRECATION_POLICIES",
    "CORS_ALLOWED_ORIGINS",
    "CORS_ALLOW_CREDENTIALS",
    "CSP_HEADER",
    "DEFAULT_IMPORT_BATCH_SIZE",
    "REST_FRAMEWORK",
    "SIMPLE_JWT",
    "SPECTACULAR_SETTINGS",
]
