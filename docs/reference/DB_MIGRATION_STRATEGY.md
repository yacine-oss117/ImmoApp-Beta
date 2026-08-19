# DB Migration Strategy

## Locked Policy

- Alembic under `server/alembic/versions/` owns physical schema truth for business tables.
- Django owns runtime model state.
- Django migrations must not blindly duplicate Alembic DDL.
- Alembic-owned tables with Django runtime models must use state-only mirrors.
- Runtime schema mode remains `IMMOAPP_SCHEMA_MODE=alembic`.
- Runtime startup is not allowed to invent or patch business DDL.

## Canonical References

- [SCHEMA_AUTHORITY.md](SCHEMA_AUTHORITY.md)
- [DB_SCHEMA_REFERENCE.md](DB_SCHEMA_REFERENCE.md)
- [DB_TABLE_CATALOG.md](DB_TABLE_CATALOG.md)
- [ADDING_SCHEMA_SAFELY.md](../guides/ADDING_SCHEMA_SAFELY.md)
- `server/pg/schema_authority_registry.py`

## Migration Style Matrix

| Situation | Physical owner | Django model? | Required approach |
| --- | --- | --- | --- |
| Django contrib/app-native table | Django | yes | normal Django migration |
| Business table with runtime ORM use | Alembic | yes | Alembic physical revision + Django `SeparateDatabaseAndState` mirror |
| Business table with no ORM use | Alembic | no | Alembic only |
| Postgres-specific index/constraint on Alembic-owned table | Alembic | maybe | Alembic only; Django state only if runtime metadata needs it |

## When `SeparateDatabaseAndState` Is Required

Use `SeparateDatabaseAndState` when all of the following are true:

1. the table or object is Alembic-owned physically
2. Django must know about the runtime model state
3. Django must not perform blind physical DDL for that object

Current state-only mirror examples:

- `imports.0006_importworkflowstate_importchunkphase_heartbeat_at`
- `imports.0007_importagencyalias_importcorrectionsignal`
- `imports.0008_importagencyprofile_importdeadletterrow`

## Authoring Rules

- Start with the registry: classify the table in `server/pg/schema_authority_registry.py`.
- If the table is Alembic-owned and mirrored, write the Alembic revision first.
- Mirror only the Django state that runtime code needs.
- Keep mirrored ORM models exact:
  - table name
  - PK shape
  - FK shape
  - nullability
  - relevant defaults
  - uniqueness
  - runtime-critical indexes and constraints
- Do not add plain Django `CreateModel` / `AddField` / `AddIndex` operations for Alembic-owned tables outside `SeparateDatabaseAndState.state_operations`.

## Mandatory Verification

Every schema wave must keep these green:

- Django model drift check
- `scripts/verify_schema_authority_registry.py`
- `scripts/verify_no_blind_django_ddl_for_alembic_owned_tables.py`
- `scripts/verify_raw_sql_orm_mirror_contract.py`
- `scripts/verify_state_only_mirror_contract.py`
- `scripts/verify_db_table_catalog.py`
- `scripts/verify_schema_authority_docs.py`
- Alembic fresh-chain verification

## Public Commands

- upgrade:
  `powershell -ExecutionPolicy Bypass -File scripts/db_migrate.ps1 -Action upgrade`
- current revision:
  `powershell -ExecutionPolicy Bypass -File scripts/db_migrate.ps1 -Action current`
- history:
  `powershell -ExecutionPolicy Bypass -File scripts/db_migrate.ps1 -Action history`

## Security Note

ALE blind trigram hashing uses the database-side `immoapp_hash_trigrams(...)`
function and `ALE_SEARCH_SECRET`.
