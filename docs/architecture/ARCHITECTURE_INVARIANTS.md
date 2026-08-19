# Architecture Invariants

These are hard rules. Refactors are allowed to move code, not to silently break
these boundaries.

## 1. Dual database boundary

- Django ORM is for identity/auth/admin and import job models
- business data is owned by psycopg unit-of-work and repository code
- new ORM use in `server/api` or `server/services` must be deliberate and
  test-allowlisted

Never:

- add ORM writes for business tables in API views
- assume Django ORM work and psycopg work share one atomic transaction
- hide business DDL behind runtime startup code

## 2. Schema ownership

- Alembic owns business-table Postgres DDL
- Django migrations own Django app and contrib tables
- runtime startup does not mutate schema except explicit maintenance paths

## 3. Runtime import boundary

- desktop runtime code under `app/` must not import `server.*`
- shared contracts belong under `core/`

## 4. Sensitive write protection

- high-risk write endpoints require step-up authentication
- step-up endpoint: `POST /api/auth/step-up/`
- proof header: `X-Immoapp-Step-Up`
- strict default: `IMMOAPP_REQUIRE_STEP_UP_SENSITIVE=1`
