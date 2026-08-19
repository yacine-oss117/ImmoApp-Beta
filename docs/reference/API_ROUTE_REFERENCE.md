# API Route Reference

Generated from the live Django URL config and the declarative `/api/v1/` route registry.
Do not hand-edit this file. Rebuild it with `python scripts/generate_api_route_reference.py`.

- root routes: 12 top-level entries
- `/api/v1/` routes: 185 registered endpoints

Use this file when you need the exact current route surface. Use
`API_VERSIONING_PAGINATION_POLICY.md` for contract rules and budgets.

## Root routes

| Path | Methods | View |
| --- | --- | --- |
| `/admin/` | include | `django.contrib.admin.site.urls` |
| `/api/schema/` | `GET` | `drf_spectacular.views.SpectacularAPIView` |
| `/api/docs/` | `GET` | `drf_spectacular.views.SpectacularSwaggerView` |
| `/api/v1/` | include | `server.api.urls` |
| `/api/auth/token/` | `POST` | `server.api.auth_views.SecureTokenObtainPairView` |
| `/api/auth/token/refresh/` | `POST` | `server.api.auth_views.SecureTokenRefreshView` |
| `/api/auth/password/forgot/` | `POST` | `server.api.auth_account_views.PasswordForgotView` |
| `/api/auth/password/reset/` | `POST` | `server.api.auth_account_views.PasswordResetView` |
| `/api/auth/account/activate/` | `POST` | `server.api.auth_account_views.AccountActivateView` |
| `/api/auth/step-up/` | `POST` | `server.api.auth_account_views.StepUpAuthView` |
| `/api/auth/oidc/config/` | `GET` | `server.api.auth_oidc_views.OidcConfigView` |
| `/api/auth/oidc/token/` | `POST` | `server.api.auth_oidc_views.OidcTokenView` |

## `/api/v1/` routes

### audit

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/audit/logs/` | `GET` | `server.api.secured_view._wrapped` | `route.audit_logs` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/audit/count/` | `GET` | `server.api.secured_view._wrapped` | `route.audit_count` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/audit/auth-events/` | `GET` | `server.api.secured_view._wrapped` | `route.audit_auth_events` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/audit/auth-events/count/` | `GET` | `server.api.secured_view._wrapped` | `route.audit_auth_events_count` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/audit/purge/` | `DELETE` | `server.api.secured_view._wrapped` | `route.audit_purge` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/audit/security-alerts/` | `GET` | `server.api.secured_view._wrapped` | `route.audit_security_alerts` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/audit/security-alerts/count/` | `GET` | `server.api.secured_view._wrapped` | `route.audit_security_alerts_count` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### auth

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/auth/register/` | `POST` | `server.api.secured_view._wrapped` | `route.auth_register` | `NO_RETRY` | `CHEAP` | `NONE` | no |
| `/api/v1/auth/register/approve/<str:signed_token>/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.auth_register_approve` | `NO_RETRY` | `CHEAP` | `NONE` | no |
| `/api/v1/auth/register/blacklist/<str:signed_token>/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.auth_register_blacklist` | `NO_RETRY` | `CHEAP` | `NONE` | no |
| `/api/v1/auth/activate/` | `POST` | `server.api.secured_view._wrapped` | `route.auth_activate` | `NO_RETRY` | `CHEAP` | `NONE` | no |
| `/api/v1/auth/accept-invite/` | `POST` | `server.api.secured_view._wrapped` | `route.auth_accept_invite` | `NO_RETRY` | `CHEAP` | `NONE` | no |
| `/api/v1/auth/mfa/totp/` | `GET` | `server.api.secured_view._wrapped` | `route.auth_mfa_totp` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/auth/mfa/totp/enroll/start/` | `POST` | `server.api.secured_view._wrapped` | `route.auth_mfa_totp_enroll_start` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/auth/mfa/totp/enroll/confirm/` | `POST` | `server.api.secured_view._wrapped` | `route.auth_mfa_totp_enroll_confirm` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/auth/mfa/totp/disable/` | `POST` | `server.api.secured_view._wrapped` | `route.auth_mfa_totp_disable` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/auth/sessions/` | `GET` | `server.api.secured_view._wrapped` | `route.auth_sessions` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/auth/sessions/<uuid:session_id>/revoke/` | `POST` | `server.api.secured_view._wrapped` | `route.auth_sessions_uuid_session_id_revoke` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/auth/sessions/revoke-all/` | `POST` | `server.api.secured_view._wrapped` | `route.auth_sessions_revoke_all` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |

### cache

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/cache/match/status/` | `GET` | `server.api.secured_view._wrapped` | `route.cache_match_status` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/cache/match/dirty/` | `GET` | `server.api.secured_view._wrapped` | `route.cache_match_dirty` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/cache/match/missing/` | `GET` | `server.api.secured_view._wrapped` | `route.cache_match_missing` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/cache/match/batch/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_batch` | `IDEMPOTENCY_KEY_WRITE` | `BOUNDED` | `FULL_SAFE` | no |
| `/api/v1/cache/match/get/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.cache_match_get` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/cache/match/all/` | `GET` | `server.api.secured_view._wrapped` | `route.cache_match_all` | `CHEAP_READ` | `EXPENSIVE` | `NONE` | no |
| `/api/v1/cache/match/count/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_count` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/cache/match/counts/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_counts` | `IDEMPOTENCY_KEY_WRITE` | `BOUNDED` | `FULL_SAFE` | no |
| `/api/v1/cache/match/mark-all/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_mark_all` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/cache/match/mark-client/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_mark_client` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/cache/match/mark-wilaya/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_mark_wilaya` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/cache/match/clear/` | `DELETE` | `server.api.secured_view._wrapped` | `route.cache_match_clear` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/cache/match/rebuild/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_rebuild` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/cache/match/rebuild/dirty/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_rebuild_dirty` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/cache/match/rebuild/client/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_rebuild_client` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/cache/match/rebuild/wilaya/` | `POST` | `server.api.secured_view._wrapped` | `route.cache_match_rebuild_wilaya` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |

### clients

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/clients/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.clients` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | yes |
| `/api/v1/clients/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.clients_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/clients/count/` | `GET` | `server.api.secured_view._wrapped` | `route.clients_count` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/clients/deleted/` | `GET` | `server.api.secured_view._wrapped` | `route.clients_deleted` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/clients/phone-duplicates/` | `GET` | `server.api.secured_view._wrapped` | `route.clients_phone_duplicates` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/clients/<int:client_id>/` | `DELETE, GET, PUT` | `server.api.secured_view._wrapped` | `route.clients_int_client_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/clients/<int:client_id>/restore/` | `POST` | `server.api.secured_view._wrapped` | `route.clients_int_client_id_restore` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/clients/<int:client_id>/purge/` | `DELETE` | `server.api.secured_view._wrapped` | `route.clients_int_client_id_purge` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/clients/<int:client_id>/demandes/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.clients_int_client_id_demandes` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |

### compliance

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/compliance/users/<int:user_id>/export/` | `POST` | `server.api.secured_view._wrapped` | `route.compliance_users_export` | `CAS_WRITE` | `BOUNDED` | `REFERENCE_ONLY` | no |
| `/api/v1/compliance/users/<int:user_id>/delete/` | `POST` | `server.api.secured_view._wrapped` | `route.compliance_users_delete` | `CAS_WRITE` | `BOUNDED` | `REFERENCE_ONLY` | no |
| `/api/v1/compliance/jobs/<uuid:job_id>/` | `GET` | `server.api.secured_view._wrapped` | `route.compliance_jobs_status` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/compliance/exports/<uuid:job_id>/download/` | `GET` | `server.api.secured_view._wrapped` | `route.compliance_exports_download` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |

### crm

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/crm/contracts/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.crm_contracts` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/contracts/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.crm_contracts_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/crm/contracts/deleted/` | `GET` | `server.api.secured_view._wrapped` | `route.crm_contracts_deleted` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/crm/contracts/<int:contract_id>/` | `DELETE, GET, PUT` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/crm/contracts/<int:contract_id>/restore/` | `POST` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id_restore` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/contracts/<int:contract_id>/purge/` | `DELETE` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id_purge` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/crm/contracts/<int:contract_id>/print/` | `POST` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id_print` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/contracts/<int:contract_id>/activate/` | `POST` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id_activate` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/contracts/<int:contract_id>/cancel/` | `POST` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id_cancel` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/contracts/<int:contract_id>/articles/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id_articles` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/contracts/<int:contract_id>/articles/renumber/` | `POST` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id_articles_renumber` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/contracts/<int:contract_id>/clauses/` | `POST` | `server.api.secured_view._wrapped` | `route.crm_contracts_int_contract_id_clauses` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/articles/<int:article_id>/` | `DELETE, PUT` | `server.api.secured_view._wrapped` | `route.crm_articles_int_article_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/crm/articles/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.crm_articles_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/crm/visits/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.crm_visits` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/visits/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.crm_visits_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/crm/visits/deleted/` | `GET` | `server.api.secured_view._wrapped` | `route.crm_visits_deleted` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/crm/visits/<int:visit_id>/` | `DELETE, PUT` | `server.api.secured_view._wrapped` | `route.crm_visits_int_visit_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/crm/visits/<int:visit_id>/restore/` | `POST` | `server.api.secured_view._wrapped` | `route.crm_visits_int_visit_id_restore` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/crm/visits/<int:visit_id>/purge/` | `DELETE` | `server.api.secured_view._wrapped` | `route.crm_visits_int_visit_id_purge` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |

### dashboard

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/dashboard/` | `GET` | `server.api.secured_view._wrapped` | `route.dashboard` | `CHEAP_READ` | `CHEAP` | `NONE` | yes |

### demandes

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/demandes/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.demandes_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/demandes/deleted/` | `GET` | `server.api.secured_view._wrapped` | `route.demandes_deleted` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/demandes/<int:demande_id>/` | `DELETE, GET, PUT` | `server.api.secured_view._wrapped` | `route.demandes_int_demande_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/demandes/<int:demande_id>/restore/` | `POST` | `server.api.secured_view._wrapped` | `route.demandes_int_demande_id_restore` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/demandes/<int:demande_id>/purge/` | `DELETE` | `server.api.secured_view._wrapped` | `route.demandes_int_demande_id_purge` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |

### diagnostics

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/diagnostics/keys/enrollment-token/` | `POST` | `server.api.secured_view._wrapped` | `route.diagnostics_keys_enrollment_token` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/diagnostics/keys/register/` | `POST` | `server.api.secured_view._wrapped` | `route.diagnostics_keys_register` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/diagnostics/keys/rotate/` | `POST` | `server.api.secured_view._wrapped` | `route.diagnostics_keys_rotate` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/diagnostics/keys/revoke/` | `POST` | `server.api.secured_view._wrapped` | `route.diagnostics_keys_revoke` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/diagnostics/verify/` | `POST` | `server.api.secured_view._wrapped` | `route.diagnostics_verify` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |

### e2e

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/e2e/runtime/identity/` | `GET` | `server.api.secured_view._wrapped` | `route.e2e_runtime_identity` | `CHEAP_READ` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/e2e/notifications/publish/` | `POST` | `server.api.secured_view._wrapped` | `route.e2e_notifications_publish` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/e2e/auth/revoke-other-sessions/` | `POST` | `server.api.secured_view._wrapped` | `route.e2e_auth_revoke_other_sessions` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/e2e/auth/revoke-session/` | `POST` | `server.api.secured_view._wrapped` | `route.e2e_auth_revoke_session` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/e2e/imports/pause-next/` | `POST` | `server.api.secured_view._wrapped` | `route.e2e_imports_pause_next` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/e2e/faults/inject/` | `POST` | `server.api.secured_view._wrapped` | `route.e2e_faults_inject` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/e2e/entities/inspect/` | `GET` | `server.api.secured_view._wrapped` | `route.e2e_entities_inspect` | `CHEAP_READ` | `CHEAP` | `FULL_SAFE` | no |

### firewall-verification

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/firewall-verification/` | `GET` | `server.api.views_health.firewall_verification` | `route.firewall_verification` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### health

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/health/` | `GET` | `server.api.secured_view._wrapped` | `route.health` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/health/live/` | `GET` | `server.api.secured_view._wrapped` | `route.health_live` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/health/ready/` | `GET` | `server.api.secured_view._wrapped` | `route.health_ready` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/health/snapshot/` | `GET` | `server.api.secured_view._wrapped` | `route.health_snapshot` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### hub

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/hub/front-door/identity/` | `GET` | `server.api.secured_view._wrapped` | `route.hub_front_door_identity` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### hub-manager

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/hub-manager/owner-state/` | `GET` | `server.api.secured_view._wrapped` | `route.hub_manager_owner_state` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/hub-manager/authorizations/` | `POST` | `server.api.secured_view._wrapped` | `route.hub_manager_authorizations` | `CAS_WRITE` | `CHEAP` | `NONE` | no |
| `/api/v1/hub-manager/authorizations/consume/` | `POST` | `server.api.secured_view._wrapped` | `route.hub_manager_authorizations_consume` | `CAS_WRITE` | `CHEAP` | `NONE` | no |

### import

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/import/upload/` | `POST` | `server.api.secured_view._wrapped` | `route.import_upload` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/import/presign/` | `POST` | `server.api.secured_view._wrapped` | `route.import_presign` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/import/complete/` | `POST` | `server.api.secured_view._wrapped` | `route.import_complete` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/import/preview/` | `POST` | `server.api.secured_view._wrapped` | `route.import_preview` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/import/execute/` | `POST` | `server.api.secured_view._wrapped` | `route.import_execute` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/import/<str:session_id>/cancel/` | `POST` | `server.api.secured_view._wrapped` | `route.import_str_session_id_cancel` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/import/status/<str:task_id>/` | `GET` | `server.api.secured_view._wrapped` | `route.import_status_str_task_id` | `CHEAP_READ` | `EXPENSIVE` | `NONE` | no |
| `/api/v1/import/<str:session_id>/review/` | `GET` | `server.api.secured_view._wrapped` | `route.import_str_session_id_review` | `CHEAP_READ` | `EXPENSIVE` | `NONE` | no |
| `/api/v1/import/<str:session_id>/review/submit/` | `POST` | `server.api.secured_view._wrapped` | `route.import_str_session_id_review_submit` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/import/admin/security-limits/` | `GET` | `server.api.secured_view._wrapped` | `route.import_admin_security_limits` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/import/admin/security-limits/reload/` | `POST` | `server.api.secured_view._wrapped` | `route.import_admin_security_limits_reload` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |

### listings

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/listings/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.listings` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | yes |
| `/api/v1/listings/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.listings_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/listings/count/` | `GET` | `server.api.secured_view._wrapped` | `route.listings_count` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/listings/deleted/` | `GET` | `server.api.secured_view._wrapped` | `route.listings_deleted` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/listings/phone-duplicates/` | `GET` | `server.api.secured_view._wrapped` | `route.listings_phone_duplicates` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/listings/<int:listing_id>/` | `DELETE, GET, PUT` | `server.api.secured_view._wrapped` | `route.listings_int_listing_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/listings/<int:listing_id>/restore/` | `POST` | `server.api.secured_view._wrapped` | `route.listings_int_listing_id_restore` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/listings/<int:listing_id>/purge/` | `DELETE` | `server.api.secured_view._wrapped` | `route.listings_int_listing_id_purge` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/listings/<int:listing_id>/offers/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.listings_int_listing_id_offers` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### locations

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/locations/` | `DELETE, GET, POST, PUT` | `server.api.secured_view._wrapped` | `route.locations` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/locations/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.locations_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |

### lookup

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/lookup/property-types/` | `GET` | `server.api.secured_view._wrapped` | `route.lookup_property_types` | `CHEAP_READ` | `CHEAP` | `NONE` | yes |
| `/api/v1/lookup/property-types/<int:type_id>/` | `GET` | `server.api.secured_view._wrapped` | `route.lookup_property_types_int_type_id` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/lookup/actions/` | `GET` | `server.api.secured_view._wrapped` | `route.lookup_actions` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/lookup/actions/<int:action_id>/` | `GET` | `server.api.secured_view._wrapped` | `route.lookup_actions_int_action_id` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/lookup/wilayas/` | `GET` | `server.api.secured_view._wrapped` | `route.lookup_wilayas` | `CHEAP_READ` | `CHEAP` | `NONE` | yes |
| `/api/v1/lookup/wilayas/<int:wilaya_id>/` | `GET` | `server.api.secured_view._wrapped` | `route.lookup_wilayas_int_wilaya_id` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### matches

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/matches/client/<int:client_id>/` | `GET` | `server.api.secured_view._wrapped` | `route.matches_client_int_client_id` | `CHEAP_READ` | `CHEAP` | `NONE` | yes |
| `/api/v1/matches/demandes/<int:demande_id>/` | `GET` | `server.api.secured_view._wrapped` | `route.matches_demandes_int_demande_id` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/matches/demandes/<int:demande_id>/expand/` | `POST` | `server.api.secured_view._wrapped` | `route.matches_demandes_int_demande_id_expand` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/matches/clients/counts/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.matches_clients_counts` | `IDEMPOTENCY_KEY_WRITE` | `BOUNDED` | `FULL_SAFE` | no |
| `/api/v1/matches/clients/all/` | `POST` | `server.api.secured_view._wrapped` | `route.matches_clients_all` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/matches/clients/wilaya/` | `GET` | `server.api.secured_view._wrapped` | `route.matches_clients_wilaya` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/matches/demandes/all/` | `POST` | `server.api.secured_view._wrapped` | `route.matches_demandes_all` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/matches/demandes/counts/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.matches_demandes_counts` | `IDEMPOTENCY_KEY_WRITE` | `BOUNDED` | `FULL_SAFE` | no |
| `/api/v1/matches/listings/counts/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.matches_listings_counts` | `IDEMPOTENCY_KEY_WRITE` | `BOUNDED` | `FULL_SAFE` | no |
| `/api/v1/matches/offers/counts/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.matches_offers_counts` | `IDEMPOTENCY_KEY_WRITE` | `BOUNDED` | `FULL_SAFE` | no |
| `/api/v1/matches/listings/all/` | `POST` | `server.api.secured_view._wrapped` | `route.matches_listings_all` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |
| `/api/v1/matches/offers/all/` | `POST` | `server.api.secured_view._wrapped` | `route.matches_offers_all` | `IDEMPOTENCY_KEY_WRITE` | `EXPENSIVE` | `FULL_SAFE` | no |

### meta

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/meta/policy/` | `GET` | `server.api.secured_view._wrapped` | `route.meta_policy` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/meta/latency/` | `GET` | `server.api.secured_view._wrapped` | `route.meta_latency` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### notifications

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/notifications/` | `GET` | `server.api.secured_view._wrapped` | `route.notifications` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/notifications/clear/` | `POST` | `server.api.secured_view._wrapped` | `route.notifications_clear` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/notifications/mark-read/` | `POST` | `server.api.secured_view._wrapped` | `route.notifications_mark_read` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/notifications/mark-unread/` | `POST` | `server.api.secured_view._wrapped` | `route.notifications_mark_unread` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/notifications/unread-count/` | `GET` | `server.api.secured_view._wrapped` | `route.notifications_unread_count` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/notifications/purge/` | `POST` | `server.api.secured_view._wrapped` | `route.notifications_purge` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |

### offers

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/offers/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.offers_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/offers/photos/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.offers_photos_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/offers/deleted/` | `GET` | `server.api.secured_view._wrapped` | `route.offers_deleted` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/offers/<int:offer_id>/` | `DELETE, GET, PUT` | `server.api.secured_view._wrapped` | `route.offers_int_offer_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/offers/<int:offer_id>/photos/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.offers_int_offer_id_photos` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/offers/photos/<int:photo_id>/` | `DELETE` | `server.api.secured_view._wrapped` | `route.offers_photos_int_photo_id` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/offers/<int:offer_id>/restore/` | `POST` | `server.api.secured_view._wrapped` | `route.offers_int_offer_id_restore` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/offers/<int:offer_id>/purge/` | `DELETE` | `server.api.secured_view._wrapped` | `route.offers_int_offer_id_purge` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |

### secrets

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/secrets/status/` | `GET` | `server.api.secured_view._wrapped` | `route.secrets_status` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### settings

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/settings/agency/` | `GET` | `server.api.secured_view._wrapped` | `route.settings_agency` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/settings/agency/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.settings_agency_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/settings/agency/set/` | `POST` | `server.api.secured_view._wrapped` | `route.settings_agency_set` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/settings/agency/serial/` | `POST` | `server.api.secured_view._wrapped` | `route.settings_agency_serial` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/settings/agency/media/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.settings_agency_media` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/settings/agency/media/presign/` | `POST` | `server.api.secured_view._wrapped` | `route.settings_agency_media_presign` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/settings/agency/media/complete/` | `POST` | `server.api.secured_view._wrapped` | `route.settings_agency_media_complete` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/settings/user/` | `GET` | `server.api.secured_view._wrapped` | `route.settings_user` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/settings/user/set/` | `POST` | `server.api.secured_view._wrapped` | `route.settings_user_set` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |

### simulation

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/simulation/start/` | `POST` | `server.api.secured_view._wrapped` | `route.simulation_start` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/simulation/delete/` | `POST` | `server.api.secured_view._wrapped` | `route.simulation_delete` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/simulation/status/` | `GET` | `server.api.secured_view._wrapped` | `route.simulation_status` | `CHEAP_READ` | `CHEAP` | `NONE` | no |
| `/api/v1/simulation/save/` | `POST` | `server.api.secured_view._wrapped` | `route.simulation_save` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |

### storage

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/storage/presign/` | `POST` | `server.api.secured_view._wrapped` | `route.storage_presign` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/storage/presign-upload/` | `POST` | `server.api.secured_view._wrapped` | `route.storage_presign_upload` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/storage/complete-upload/` | `POST` | `server.api.secured_view._wrapped` | `route.storage_complete_upload` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/storage/delete/` | `POST` | `server.api.secured_view._wrapped` | `route.storage_delete` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |

### tasks

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/tasks/<str:task_id>/` | `GET` | `server.api.secured_view._wrapped` | `route.tasks_str_task_id` | `CHEAP_READ` | `CHEAP` | `NONE` | no |

### templates

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/templates/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.templates` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/templates/changes/` | `GET` | `server.api.secured_view._wrapped` | `route.templates_changes` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |
| `/api/v1/templates/<int:template_id>/` | `DELETE, GET, PUT` | `server.api.secured_view._wrapped` | `route.templates_int_template_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/templates/reset-defaults/` | `POST` | `server.api.secured_view._wrapped` | `route.templates_reset_defaults` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |

### users

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/users/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.users` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/users/<int:user_id>/` | `DELETE, GET, PUT` | `server.api.secured_view._wrapped` | `route.users_int_user_id` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/users/invites/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.users_invites` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/users/invites/<uuid:invite_id>/resend/` | `POST` | `server.api.secured_view._wrapped` | `route.users_invites_uuid_invite_id_resend` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
| `/api/v1/users/invites/<uuid:invite_id>/revoke/` | `POST` | `server.api.secured_view._wrapped` | `route.users_invites_uuid_invite_id_revoke` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/users/permissions/grants/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.users_permissions_grants` | `IDEMPOTENCY_KEY_WRITE` | `BOUNDED` | `FULL_SAFE` | no |
| `/api/v1/users/permissions/grants/<int:request_id>/approve/` | `POST` | `server.api.secured_view._wrapped` | `route.users_permissions_grants_int_request_id_approve` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/users/permissions/grants/<int:request_id>/deny/` | `POST` | `server.api.secured_view._wrapped` | `route.users_permissions_grants_int_request_id_deny` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/users/permissions/grants/<int:request_id>/revoke/` | `POST` | `server.api.secured_view._wrapped` | `route.users_permissions_grants_int_request_id_revoke` | `CAS_WRITE` | `CHEAP` | `REFERENCE_ONLY` | no |
| `/api/v1/users/permissions/matrix/` | `GET` | `server.api.secured_view._wrapped` | `route.users_permissions_matrix` | `CHEAP_READ` | `BOUNDED` | `NONE` | no |

### visibility

| Path | Methods | View | Policy | Retry | Cost | Replay | SLA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/visibility/<str:table>/<int:record_id>/` | `GET, POST` | `server.api.secured_view._wrapped` | `route.visibility_str_table_int_record_id` | `IDEMPOTENCY_KEY_WRITE` | `CHEAP` | `FULL_SAFE` | no |
