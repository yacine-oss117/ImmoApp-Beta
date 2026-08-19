# Database Schema Reference

## Scope

This is the high-level production schema reference.

- Alembic owns physical DDL for business tables.
- Django owns runtime model state.
- Django-owned app/contrib tables remain Django-native.
- Runtime startup does not create or mutate business schema.

Use the generated authority catalog for exact ownership:

- [SCHEMA_AUTHORITY.md](SCHEMA_AUTHORITY.md)
- [DB_TABLE_CATALOG.md](DB_TABLE_CATALOG.md)

Use [DB_MIGRATION_STRATEGY.md](DB_MIGRATION_STRATEGY.md)
for migration rules and
[ADDING_SCHEMA_SAFELY.md](../guides/ADDING_SCHEMA_SAFELY.md)
for the authoring workflow.

## Core Domains

Identity and tenancy:

- `accounts_agency`
- `accounts_user`

CRM entities:

- `clients`
- `demandes`
- `listings`
- `offers`
- `visits`
- `contracts`
- `contract_articles`

Matching and location shape:

- `demande_locations`
- `offer_locations`
- `match_candidates`
- `match_pairs`
- `match_counts_cache`
- `match_rebuild_state`

Security and audit:

- `record_acl`
- `audit_logs`
- `task_failures`

Storage:

- `storage_objects`
- `storage_events`

Reference and settings:

- `locations`
- `property_types`
- `actions`
- `wilayas`
- `agency_settings`
- `wa_templates`

Importer runtime mirrors:

- `imports_importworkflowstate`
- `imports_importagencyalias`
- `imports_importcorrectionsignal`
- `imports_importagencyprofile`
- `imports_importdeadletterrow`

## Ownership Model

### Alembic physical truth

Alembic under `server/alembic/versions/` is the physical owner for:

- business tables
- Postgres-specific indexes and constraints
- security-sensitive DDL
- performance-sensitive DDL
- importer runtime tables mirrored into Django

### Django runtime state

Django models exist for runtime code, tests, and admin-facing access where needed.
For Alembic-owned mirrored tables, Django tracks state through
`SeparateDatabaseAndState` bridges instead of blind physical DDL.

### Django-native tables

Django app/contrib tables stay Django-owned physically. The current notable
hybrid case is `imports_importchunkphase`: the table stays Django-owned, while
Alembic revision `20260312_0025` defensively bridge-adds `heartbeat_at` when
that column is absent on fresh-chain/bootstrap paths.

## Tenant Isolation

Tenant isolation is a hard database concern, not just an API rule.

- tenant-owned rows carry `agency_id`
- PostgreSQL `RLS` is enabled on tenant-owned business tables
- `FORCE RLS` is used so table owners do not bypass policy accidentally
- request/task code sets tenant context through `app.current_agency_id`

Verification gates include:

- `scripts/verify_security_schema.py`
- `app/tests/server_tests/test_rls_breach_matrix.py`
- `app/tests/server_tests/test_api_cross_tenant_breach.py`

## Relationship Model

At a high level:

- an agency owns users, clients, listings, storage objects, and other tenant data
- a client owns many `demandes`
- a listing owns many `offers`
- contracts and visits bridge CRM workflow across client and listing sides
- matching uses location junction tables plus candidate/pair/cache state

## Write Semantics

- business rows use explicit Alembic migrations, not runtime auto-DDL
- mirrored importer runtime tables use Alembic physical truth plus Django state-only mirrors
- optimistic concurrency uses `row_version` where the workflow requires compare-and-swap protection
- soft delete is represented with `deleted_at` on applicable tables
- matching cache and rebuild state are durable tables, not transient in-memory state

## Performance and Indexing

The schema is indexed around a few hot paths:

- tenant-scoped reads by `agency_id`
- lifecycle/status filtering
- location and matching joins
- cache reads on `match_counts_cache`
- storage lifecycle reads on `storage_objects`
- importer workflow state/status reads on `imports_importworkflowstate`

Guardrails:

- `scripts/verify_query_budgets.py`
- `scripts/verify_load_baseline.py`
- mirror-contract verifiers in the PR/full lanes

## Operational Rules

- production migration mode is `IMMOAPP_SCHEMA_MODE=alembic`
- deploy/restore flows must run explicit prepare or migrate steps
- fresh-chain and Django model drift are mandatory
- generated ownership docs must stay in sync with the registry
- restore drill posture is enforced separately in the runbooks and verifier set

Bootstrap/repair note:

- admin-side raw SQL remains an intentional tool for bootstrap and repair flows
- this does not replace normal runtime write ownership through services, UoW,
  and `on_commit` side effects
- the default-agency bootstrap helper is a one-off admin repair path and now
  runs inside one admin transaction with post-repair verification
