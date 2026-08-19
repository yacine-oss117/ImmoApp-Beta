# Auth And Security

This document explains the current auth, registration, step-up, and
permission-lifecycle surface.

## What It Owns

This subsystem owns:

- username/password JWT login
- session-aware refresh, session validation, and session revocation
- password reset and account-action token flows
- owner registration review, activation, and team invite acceptance
- optional OIDC login
- TOTP MFA enrollment and verification
- step-up authentication for sensitive actions
- temporary privilege elevation
- auth/security event logging
- request-scoped tenant and actor context for database access

This is broader than login. It is the runtime identity and authorization
surface of the app.

## Public Entry Surface

Root auth URLs are mounted in:

- `server/immoapp_server/urls.py`

Important root endpoints:

- `/api/auth/token/`
- `/api/auth/token/refresh/`
- `/api/auth/password/forgot/`
- `/api/auth/password/reset/`
- `/api/auth/account/activate/`
- `/api/auth/step-up/`
- `/api/auth/oidc/config/`
- `/api/auth/oidc/token/`

Additional `/api/v1/` auth/security routes:

- `auth/register/`
- `auth/register/approve/<signed_token>/`
- `auth/register/blacklist/<signed_token>/`
- `auth/activate/`
- `auth/accept-invite/`
- `auth/mfa/totp/`
- `auth/mfa/totp/enroll/start/`
- `auth/mfa/totp/enroll/confirm/`
- `auth/mfa/totp/disable/`
- `auth/sessions/`
- `auth/sessions/<session_id>/revoke/`
- `auth/sessions/revoke-all/`
- `users/permissions/grants/`
- `users/permissions/grants/<request_id>/approve/`
- `users/permissions/grants/<request_id>/deny/`
- `users/permissions/grants/<request_id>/revoke/`
- `users/permissions/matrix/`

Primary view owners:

- `server/api/auth_views.py`
- `server/api/auth_account_views.py`
- `server/api/auth_oidc_views.py`
- `server/api/views_registration.py`
- `server/api/views_mfa.py`
- `server/api/views_auth_sessions.py`
- `server/api/views_user_permissions.py`
- `server/api/step_up.py`

Important rule:

- these views remain security boundaries
- step-up, lockout, and denial-path behavior were not moved into broad generic
  helpers during the recent refactors

## Main Service Owners

Session lifecycle:

- `server/api/auth_session_jwt.py`
- `server/services/auth_sessions.py`
- `server/services/session_lifecycle.py`
- `server/services/session_revocation.py`

Password reset and account-action tokens:

- `server/services/user_auth_lifecycle.py`
- `server/services/auth_token_actions.py`

Registration and team invites:

- `server/services/registration_lifecycle.py`
- `server/services/registration_tokens.py`
- `server/services/registration_approval.py`
- `server/services/registration_invites.py`

Privilege elevation:

- `server/services/permission_elevation.py`
- `server/services/permission_grant_queries.py`
- `server/services/permission_grant_workflow.py`

OIDC and MFA:

- `server/services/oidc_auth.py`
- `server/services/mfa_service.py`
- `server/services/mfa_totp.py`

Security telemetry and hardening:

- `server/services/auth_events.py`
- `server/services/auth_lockout.py`
- `server/services/auth_security_alerts.py`

## Current Ownership Map

High-signal current split:

- session public seam:
  - `server/services/auth_sessions.py`
- session internals:
  - `server/services/session_lifecycle.py`
  - `server/services/session_revocation.py`
- password reset and account-action orchestration:
  - `server/services/user_auth_lifecycle.py`
- `UserActionToken` mechanics for that subsystem:
  - `server/services/auth_token_actions.py`
- registration compatibility seam:
  - `server/services/registration_lifecycle.py`
- registration mechanical helpers:
  - `server/services/registration_tokens.py`
- registration review/approval/activation workflow:
  - `server/services/registration_approval.py`
- team invite workflow:
  - `server/services/registration_invites.py`
- privilege elevation public seam:
  - `server/services/permission_elevation.py`
- privilege elevation queries:
  - `server/services/permission_grant_queries.py`
- privilege elevation workflow mutations:
  - `server/services/permission_grant_workflow.py`

Important current design rules:

- `registration_lifecycle.py` remains a compatibility-heavy facade because
  tests monkeypatch its module-local seams directly
- `user_auth_lifecycle.py` still owns the public password reset and account
  action flows; `auth_token_actions.py` only owns token mechanics
- `auth_sessions.py` stays as the stable public session seam
- `permission_elevation.py` stays as the stable public privilege-elevation seam
- token purpose boundaries remain intentionally separate across:
  - password reset / invite activation via `UserActionToken`
  - registration approval / activation codes
  - step-up proofs

## Persistence Owners

Django account models:

- `server/accounts/models.py`

Important models:

- `User`
- `UserSession`
- `UserActionToken`
- `PrivilegeElevationRequest`
- `ComplianceJob`

Important SQL table outside Django business ORM:

- `auth_security_events`

Important behaviors:

- session rows track issued login sessions and revocations
- action tokens are hashed and purpose-scoped
- privilege elevation requests are durable approval records
- auth security events are append-only audit records

## Login And Session Flow

Password login:

1. request hits `server/api/auth_views.py`
2. secure token view normalizes timing and avoids account enumeration
3. serializer in `server/api/auth_session_jwt.py` authenticates user
4. MFA can be required based on user role or enrollment
5. `server/services/auth_sessions.py` issues a `UserSession`
6. `server/services/session_lifecycle.py` owns the actual issuance and refresh
   binding mechanics behind that facade
7. refresh token gets `sid`
8. refresh token JTI is bound to the session

Refresh flow:

1. refresh endpoint validates the refresh token
2. session state is rechecked through `validate_token_session()`
3. `server/services/session_lifecycle.py` rechecks `sid`, expiry, revoke
   state, and `session_invalid_before`
4. rotated refresh JTI is rebound if needed

Request authentication flow:

1. `SessionAwareJWTAuthentication` authenticates the JWT
2. if session tracking is enabled, it rejects revoked or expired sessions
3. session listing and revoke operations go through
   `server/services/session_revocation.py`

Production config:

- strict production mode requires
  `IMMOAPP_AUTH_SESSION_TRACKING_ENABLED=1` to be paired with
  `IMMOAPP_REQUIRE_SESSION_ID_CLAIM=1`
- tokens without `sid` are rejected under that production posture
- local/dev compatibility can explicitly set
  `IMMOAPP_REQUIRE_SESSION_ID_CLAIM=0`, but that is not accepted by strict
  production verification when session tracking is enabled
- boolean env values for this session contract are parsed through the shared
  repo boolean contract: truthy values are `1`, `true`, `yes`, and `on`;
  falsy values are unset, empty string, `0`, `false`, `no`, and `off`;
  invalid values fail strict production verification
- `core/env_flags.py` is the single owner for security-sensitive production
  boolean parsing; strict production verification uses that same contract for
  session tracking, required `sid` claims, OpenBao TLS verification, SSL
  redirect, and secure session/CSRF cookie flags

## Password Reset, Activation, Registration, Invite

Password reset and account-action token logic lives in:

- `server/services/user_auth_lifecycle.py`
- `server/services/auth_token_actions.py`

Agency/owner registration and invite acceptance live in:

- `server/services/registration_lifecycle.py`
- `server/services/registration_tokens.py`
- `server/services/registration_approval.py`
- `server/services/registration_invites.py`

Important properties:

- reset requests are non-disclosing
- `UserActionToken` rows are hashed before persistence
- activation/invite flows can issue sessions and JWTs on success
- registration approval tokens and activation codes are not merged with
  `UserActionToken`
- `registration_lifecycle.py` remains the public/runtime and test seam even
  though approval/invite mechanics now live in narrower helper modules

## MFA And Step-Up

TOTP MFA lifecycle:

- start enrollment
- confirm enrollment
- disable
- status check

Step-up authentication is a separate proof for sensitive actions.

Key file:

- `server/api/step_up.py`

Pattern:

1. authenticated user posts password, and sometimes MFA code, to `/api/auth/step-up/`
2. server returns short-lived `X-Immoapp-Step-Up` proof
3. sensitive endpoints call `require_step_up(request)`

Endpoints guarded by step-up include:

- session revocation
- MFA enrollment/disable
- user mutations
- permission grant approval/denial/revocation
- compliance export/delete
- diagnostics key operations

## OIDC

OIDC is optional and isolated behind:

- `server/services/oidc_auth.py`
- `server/api/auth_oidc_views.py`

Behavior:

- discovery and JWKS fetch are cached
- ID tokens are verified locally
- successful verification still ends by issuing local JWTs

OIDC is therefore an alternate login source, not a separate authorization
system.

## Tenant And Actor Context

Request and task DB context is enforced through:

- `server/api/secured_view.py`
- `server/pg/uow.py`

Important behavior:

- authenticated API views enter tenant security context
- actor id/email/role/owner flags are also attached to context
- the DB layer uses this for RLS-safe reads/writes and audit attribution

This is one of the main security boundaries in the backend.

## Privilege Elevation And Auditing

Temporary privilege elevation is not an ad hoc flag.

It is a workflow with:

- request
- approval or denial
- expiry
- revocation

Owner files:

- `server/services/permission_elevation.py`
- `server/services/permission_grant_queries.py`
- `server/services/permission_grant_workflow.py`
- `server/api/views_user_permissions.py`

Security telemetry is centralized in:

- `server/services/auth_events.py`
- `core/data/auth_security_events.py`

That event log is used across login, token refresh, step-up, MFA, privilege
elevation, registration, invites, and other sensitive actions.

## Desktop Client Surface

Main client security facade:

- `app/services/security_repository.py`

Other important client modules:

- `app/services/api_client_auth.py`
- `app/services/user_context.py`
- `app/services/registration_repository.py`

The desktop client handles:

- login and token refresh requests
- MFA enrollment UX
- session listing and revocation
- permission grant workflows
- compliance export/delete initiation

Server-side proof and enforcement remain authoritative.

## Where To Debug

Login or refresh failures:

- `server/api/auth_views.py`
- `server/api/auth_session_jwt.py`
- `server/services/auth_sessions.py`
- `server/services/session_lifecycle.py`
- `server/services/session_revocation.py`

Password reset or account-action token problems:

- `server/services/user_auth_lifecycle.py`
- `server/services/auth_token_actions.py`

Registration, activation, or invite problems:

- `server/services/registration_lifecycle.py`
- `server/services/registration_tokens.py`
- `server/services/registration_approval.py`
- `server/services/registration_invites.py`

Step-up or MFA issues:

- `server/api/auth_account_views.py`
- `server/api/step_up.py`
- `server/services/mfa_service.py`

OIDC issues:

- `server/services/oidc_auth.py`
- `server/api/auth_oidc_views.py`

Authorization or tenant-scope issues:

- `server/api/secured_view.py`
- `server/pg/uow.py`
- `server/services/permission_elevation.py`
- `server/services/permission_grant_queries.py`
- `server/services/permission_grant_workflow.py`
