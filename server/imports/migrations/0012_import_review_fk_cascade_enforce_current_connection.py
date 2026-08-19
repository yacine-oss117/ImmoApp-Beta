from __future__ import annotations

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

FORWARD_SQL = """
DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT con.conname INTO constraint_name
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE con.contype = 'f'
      AND rel.relname = 'imports_importreviewgroup'
      AND pg_get_constraintdef(con.oid) LIKE 'FOREIGN KEY (job_id)%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE imports_importreviewgroup DROP CONSTRAINT %I', constraint_name);
    END IF;
END $$;

ALTER TABLE imports_importreviewgroup
ADD CONSTRAINT imports_irgrp_job_fk_impjob
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT con.conname INTO constraint_name
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE con.contype = 'f'
      AND rel.relname = 'imports_importreviewitem'
      AND pg_get_constraintdef(con.oid) LIKE 'FOREIGN KEY (job_id)%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE imports_importreviewitem DROP CONSTRAINT %I', constraint_name);
    END IF;
END $$;

ALTER TABLE imports_importreviewitem
ADD CONSTRAINT imports_iritm_job_fk_impjob
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT con.conname INTO constraint_name
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE con.contype = 'f'
      AND rel.relname = 'imports_importreviewitem'
      AND pg_get_constraintdef(con.oid) LIKE 'FOREIGN KEY (group_id)%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE imports_importreviewitem DROP CONSTRAINT %I', constraint_name);
    END IF;
END $$;

ALTER TABLE imports_importreviewitem
ADD CONSTRAINT imports_iritm_group_fk_irgrp
FOREIGN KEY (group_id) REFERENCES imports_importreviewgroup(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;
"""

REVERSE_SQL = """
ALTER TABLE imports_importreviewitem
DROP CONSTRAINT IF EXISTS imports_iritm_group_fk_irgrp;
ALTER TABLE imports_importreviewitem
ADD CONSTRAINT imports_iritm_group_fk_irgrp
FOREIGN KEY (group_id) REFERENCES imports_importreviewgroup(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importreviewitem
DROP CONSTRAINT IF EXISTS imports_iritm_job_fk_impjob;
ALTER TABLE imports_importreviewitem
ADD CONSTRAINT imports_iritm_job_fk_impjob
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importreviewgroup
DROP CONSTRAINT IF EXISTS imports_irgrp_job_fk_impjob;
ALTER TABLE imports_importreviewgroup
ADD CONSTRAINT imports_irgrp_job_fk_impjob
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
DEFERRABLE INITIALLY DEFERRED;
"""


def _run_sql(*, schema_editor: BaseDatabaseSchemaEditor, sql: str) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql)


def apply_forward_fk_cascade_contract(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    del apps
    _run_sql(schema_editor=schema_editor, sql=FORWARD_SQL)


def apply_reverse_fk_cascade_contract(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    del apps
    _run_sql(schema_editor=schema_editor, sql=REVERSE_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0011_import_review_fk_cascade_contract"),
    ]

    operations = [
        migrations.RunPython(
            code=apply_forward_fk_cascade_contract,
            reverse_code=apply_reverse_fk_cascade_contract,
        ),
    ]
