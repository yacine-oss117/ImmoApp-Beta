# Adding Schema Safely

## Goal

Use this guide whenever you add or change a table, index, or constraint.
Follow it in order. Do not improvise around ownership.

## Step 1: Classify Ownership

Ask one question first:

`Is this a business/runtime table or a Django-native app/contrib table?`

Use this matrix:

| Situation | Physical owner | Django model? | Required approach |
| --- | --- | --- | --- |
| Django contrib/app-native table | Django | yes | normal Django migration |
| Business table with runtime ORM use | Alembic | yes | Alembic physical revision + Django `SeparateDatabaseAndState` mirror |
| Business table with no ORM use | Alembic | no | Alembic only |
| Postgres-specific index/constraint on Alembic-owned table | Alembic | maybe | Alembic only; Django state only if runtime metadata needs it |

## Step 2: Update the Registry First

Edit `server/pg/schema_authority_registry.py`.

Every new table must declare:

- `table_name`
- `owner`
- `mirror_strategy`
- `orm_model`
- `creating_alembic_revision`
- `creating_django_migration`
- `notes` when there is any legacy nuance

If the table is not in the registry, CI should fail.

## Step 3: Write the Physical Migration in the Correct System

### Alembic-owned business table

1. add the Alembic revision
2. create the table/index/constraint there
3. keep Postgres-specific DDL in Alembic

### Django-owned table

1. add the normal Django migration
2. do not add a matching Alembic table creation revision

## Step 4: Add the Django Runtime Mirror if Needed

If the table is Alembic-owned and Django needs the model:

1. add/update the Django model
2. use `SeparateDatabaseAndState`
3. keep physical DB work in `database_operations` as no-op-safe raw SQL bridge ops
4. keep model state in `state_operations`
5. do not use plain top-level `CreateModel` / `AddField` / `AddIndex` for the Alembic-owned table

Current examples:

- `imports.0006_importworkflowstate_importchunkphase_heartbeat_at`
- `imports.0007_importagencyalias_importcorrectionsignal`
- `imports.0008_importagencyprofile_importdeadletterrow`

## Step 5: Keep the Mirror Exact

For every Alembic-owned mirrored model, the Django model must exactly match:

- table name
- PK shape
- FK shape
- nullability
- relevant defaults
- uniqueness
- runtime-critical indexes and constraints

If the physical SQL says `agency_id` is the PK, the Django model must also make
that relation `primary_key=True`.

## Step 6: Rebuild the Generated Docs

Run:

```powershell
python scripts/generate_schema_authority.py
python scripts/generate_db_table_catalog.py
```

## Step 7: Run the Contract Verifiers

At minimum:

```powershell
python scripts/verify_schema_authority_registry.py
python scripts/verify_no_blind_django_ddl_for_alembic_owned_tables.py
python scripts/verify_raw_sql_orm_mirror_contract.py
python scripts/verify_state_only_mirror_contract.py
python scripts/verify_schema_authority_docs.py
python scripts/verify_db_table_catalog.py
```

Then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\checks.ps1 -Stage pr
powershell -NoProfile -ExecutionPolicy Bypass -File .\checks.ps1 -Stage full
```

## Copy-Paste Safe Templates

### Alembic-owned table with Django mirror

1. add Alembic revision for physical DDL
2. add Django model
3. add Django migration with:
   - `migrations.SeparateDatabaseAndState(...)`
   - `RunSQL(...)` in `database_operations`
   - `CreateModel` / `AddIndex` / `AddConstraint` in `state_operations`

### Django-native table

1. add Django model
2. add normal Django migration
3. do not add a matching Alembic table creation

### Alembic-only object with no ORM model

1. add Alembic revision only
2. registry entry gets `mirror_strategy="none"` and `orm_model=None`

## Never Do This

- do not add blind Django physical DDL for an Alembic-owned table
- do not change a mirrored ORM model without updating the mirror migration/state contract
- do not add a new business table without a registry entry
- do not hand-edit generated schema authority docs
