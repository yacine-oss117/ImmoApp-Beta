# Schema Authority

Generated from `server/pg/schema_authority_registry.py`.
Do not hand-edit this file. Rebuild it with `python scripts/generate_schema_authority.py`.

- registered contracts: 69
- Alembic physical tables: 43
- Django physical tables: 26
- state-only mirrors: 5

## Locked Policy

- Alembic owns physical schema truth for business tables.
- Django owns runtime model state.
- Django migrations must not blindly duplicate Alembic DDL.
- Every mirrored ORM model must exactly match its raw-SQL/state contract.
- Fresh-chain and Django model-drift checks remain mandatory release gates.

## State-Only Mirror Migrations

| Table | Owner | Mirror | ORM Model | Alembic Revision | Django Migration | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `imports_importagencyalias` | `alembic_physical` | `state_only_mirror` | `imports.ImportAgencyAlias` | `20260313_0026` | `imports.0007_importagencyalias_importcorrectionsignal` |  |
| `imports_importagencyprofile` | `alembic_physical` | `state_only_mirror` | `imports.ImportAgencyProfile` | `20260313_0027` | `imports.0008_importagencyprofile_importdeadletterrow` |  |
| `imports_importcorrectionsignal` | `alembic_physical` | `state_only_mirror` | `imports.ImportCorrectionSignal` | `20260313_0026` | `imports.0007_importagencyalias_importcorrectionsignal` |  |
| `imports_importdeadletterrow` | `alembic_physical` | `state_only_mirror` | `imports.ImportDeadLetterRow` | `20260313_0027` | `imports.0008_importagencyprofile_importdeadletterrow` |  |
| `imports_importworkflowstate` | `alembic_physical` | `state_only_mirror` | `imports.ImportWorkflowState` | `20260312_0025` | `imports.0006_importworkflowstate_importchunkphase_heartbeat_at` | Legacy bridge table reconciled as Alembic physical truth plus Django state mirror. |

## Alembic Physical Ownership

| Table | Owner | Mirror | ORM Model | Alembic Revision | Django Migration | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `actions` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `agency_settings` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `api_idempotency_records` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `api_rebuild_job_leases` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `audit_logs` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `auth_security_events` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `clients` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `contract_articles` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `contracts` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `custom_locations` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `demande_locations` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `demandes` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `imports_importagencyalias` | `alembic_physical` | `state_only_mirror` | `imports.ImportAgencyAlias` | `20260313_0026` | `imports.0007_importagencyalias_importcorrectionsignal` |  |
| `imports_importagencyprofile` | `alembic_physical` | `state_only_mirror` | `imports.ImportAgencyProfile` | `20260313_0027` | `imports.0008_importagencyprofile_importdeadletterrow` |  |
| `imports_importcorrectionsignal` | `alembic_physical` | `state_only_mirror` | `imports.ImportCorrectionSignal` | `20260313_0026` | `imports.0007_importagencyalias_importcorrectionsignal` |  |
| `imports_importdeadletterrow` | `alembic_physical` | `state_only_mirror` | `imports.ImportDeadLetterRow` | `20260313_0027` | `imports.0008_importagencyprofile_importdeadletterrow` |  |
| `imports_importworkflowstate` | `alembic_physical` | `state_only_mirror` | `imports.ImportWorkflowState` | `20260312_0025` | `imports.0006_importworkflowstate_importchunkphase_heartbeat_at` | Legacy bridge table reconciled as Alembic physical truth plus Django state mirror. |
| `listings` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `locations` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `match_artifact_health_samples` | `alembic_physical` | `none` | `-` | `20260330_0030` | `-` |  |
| `match_artifact_timeout_counters` | `alembic_physical` | `none` | `-` | `20260330_0030` | `-` |  |
| `match_candidates` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `match_counts_cache` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `match_pairs` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `match_rebuild_state` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `meta` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `notification_reads` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `notifications` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `offer_locations` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `offer_photos` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `offers` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `property_types` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `record_acl` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `storage_events` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `storage_objects` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `storage_usage` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `surface_cache_generation` | `alembic_physical` | `none` | `-` | `20260330_0029` | `-` |  |
| `task_failures` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `task_scan_checkpoints` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `tenant_work_lease` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `visits` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `wa_templates` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |
| `wilayas` | `alembic_physical` | `none` | `-` | `bootstrap_ahead_of_tracked_revisions` | `-` |  |

## Django Physical Ownership

| Table | Owner | Mirror | ORM Model | Alembic Revision | Django Migration | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `accounts_agency` | `django_physical` | `django_native` | `accounts.Agency` | `-` | `accounts (django-native app table)` |  |
| `accounts_compliancejob` | `django_physical` | `django_native` | `accounts.ComplianceJob` | `-` | `accounts (django-native app table)` |  |
| `accounts_diagnosticsenrollmenttoken` | `django_physical` | `django_native` | `accounts.DiagnosticsEnrollmentToken` | `-` | `accounts (django-native app table)` |  |
| `accounts_diagnosticssigningkey` | `django_physical` | `django_native` | `accounts.DiagnosticsSigningKey` | `-` | `accounts (django-native app table)` |  |
| `accounts_emailoutbox` | `django_physical` | `django_native` | `accounts.EmailOutbox` | `-` | `accounts (django-native app table)` |  |
| `accounts_privilegeelevationrequest` | `django_physical` | `django_native` | `accounts.PrivilegeElevationRequest` | `-` | `accounts (django-native app table)` |  |
| `accounts_registrationrequest` | `django_physical` | `django_native` | `accounts.RegistrationRequest` | `-` | `accounts (django-native app table)` |  |
| `accounts_user` | `django_physical` | `django_native` | `accounts.User` | `-` | `accounts (django-native app table)` |  |
| `accounts_useractiontoken` | `django_physical` | `django_native` | `accounts.UserActionToken` | `-` | `accounts (django-native app table)` |  |
| `accounts_userinvite` | `django_physical` | `django_native` | `accounts.UserInvite` | `-` | `accounts (django-native app table)` |  |
| `accounts_usersession` | `django_physical` | `django_native` | `accounts.UserSession` | `-` | `accounts (django-native app table)` |  |
| `auth_group` | `django_physical` | `django_native` | `auth.Group` | `-` | `django.contrib.auth (framework-managed)` |  |
| `auth_permission` | `django_physical` | `django_native` | `auth.Permission` | `-` | `django.contrib.auth (framework-managed)` |  |
| `django_admin_log` | `django_physical` | `django_native` | `admin.LogEntry` | `-` | `django.contrib.admin (framework-managed)` |  |
| `django_content_type` | `django_physical` | `django_native` | `contenttypes.ContentType` | `-` | `django.contrib.contenttypes (framework-managed)` |  |
| `django_migrations` | `django_physical` | `django_native` | `-` | `-` | `django migration recorder (framework-managed)` |  |
| `django_session` | `django_physical` | `django_native` | `sessions.Session` | `-` | `django.contrib.sessions (framework-managed)` |  |
| `imports_importartifactmanifest` | `django_physical` | `django_native` | `imports.ImportArtifactManifest` | `-` | `imports (django-native app table)` |  |
| `imports_importchunk` | `django_physical` | `django_native` | `imports.ImportChunk` | `-` | `imports (django-native app table)` |  |
| `imports_importchunkphase` | `django_physical` | `django_native` | `imports.ImportChunkPhase` | `-` | `imports (django-native app table)` | Legacy Django-owned table. Alembic revision 20260312_0025 bridge-adds heartbeat_at when absent, but table ownership remains Django. |
| `imports_importjob` | `django_physical` | `django_native` | `imports.ImportJob` | `-` | `imports (django-native app table)` |  |
| `imports_importreviewgroup` | `django_physical` | `django_native` | `imports.ImportReviewGroup` | `-` | `imports (django-native app table)` |  |
| `imports_importreviewitem` | `django_physical` | `django_native` | `imports.ImportReviewItem` | `-` | `imports (django-native app table)` |  |
| `imports_importrowaudit` | `django_physical` | `django_native` | `imports.ImportRowAudit` | `-` | `imports (django-native app table)` |  |
| `token_blacklist_blacklistedtoken` | `django_physical` | `django_native` | `token_blacklist.BlacklistedToken` | `-` | `rest_framework_simplejwt.token_blacklist (framework-managed)` |  |
| `token_blacklist_outstandingtoken` | `django_physical` | `django_native` | `token_blacklist.OutstandingToken` | `-` | `rest_framework_simplejwt.token_blacklist (framework-managed)` |  |
