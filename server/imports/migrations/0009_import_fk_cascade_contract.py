from __future__ import annotations

import os

import psycopg
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

FORWARD_SQL = """
ALTER TABLE imports_importjob
DROP CONSTRAINT IF EXISTS imports_importjob_user_id_2e56696d_fk_accounts_user_id;
ALTER TABLE imports_importjob
ADD CONSTRAINT imports_importjob_user_id_2e56696d_fk_accounts_user_id
FOREIGN KEY (user_id) REFERENCES accounts_user(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importjob
DROP CONSTRAINT IF EXISTS imports_importjob_agency_id_08860415_fk_accounts_agency_id;
ALTER TABLE imports_importjob
ADD CONSTRAINT imports_importjob_agency_id_08860415_fk_accounts_agency_id
FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importrowaudit
DROP CONSTRAINT IF EXISTS imports_importrowaudit_job_id_a2a95616_fk_imports_importjob_id;
ALTER TABLE imports_importrowaudit
ADD CONSTRAINT imports_importrowaudit_job_id_a2a95616_fk_imports_importjob_id
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importrowaudit
DROP CONSTRAINT IF EXISTS imports_importrowaudit_agency_id_b2e4ddf8_fk_accounts_agency_id;
ALTER TABLE imports_importrowaudit
ADD CONSTRAINT imports_importrowaudit_agency_id_b2e4ddf8_fk_accounts_agency_id
FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importrowaudit
DROP CONSTRAINT IF EXISTS imports_importrowaudit_actor_id_98390f30_fk_accounts_user_id;
ALTER TABLE imports_importrowaudit
ADD CONSTRAINT imports_importrowaudit_actor_id_98390f30_fk_accounts_user_id
FOREIGN KEY (actor_id) REFERENCES accounts_user(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importchunk
DROP CONSTRAINT IF EXISTS imports_importchunk_job_id_ff1859ae_fk_imports_importjob_id;
ALTER TABLE imports_importchunk
ADD CONSTRAINT imports_importchunk_job_id_ff1859ae_fk_imports_importjob_id
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importchunk
DROP CONSTRAINT IF EXISTS imports_importchunk_agency_id_24f93a59_fk_accounts_agency_id;
ALTER TABLE imports_importchunk
ADD CONSTRAINT imports_importchunk_agency_id_24f93a59_fk_accounts_agency_id
FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importchunkphase
DROP CONSTRAINT IF EXISTS imports_importchunkp_chunk_id_e6c7877a_fk_imports_i;
ALTER TABLE imports_importchunkphase
ADD CONSTRAINT imports_importchunkp_chunk_id_e6c7877a_fk_imports_i
FOREIGN KEY (chunk_id) REFERENCES imports_importchunk(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importartifactmanifest
DROP CONSTRAINT IF EXISTS imports_importartifa_job_id_9acce294_fk_imports_i;
ALTER TABLE imports_importartifactmanifest
ADD CONSTRAINT imports_importartifa_job_id_9acce294_fk_imports_i
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importartifactmanifest
DROP CONSTRAINT IF EXISTS imports_importartifa_agency_id_ec0fd5bd_fk_accounts_;
ALTER TABLE imports_importartifactmanifest
ADD CONSTRAINT imports_importartifa_agency_id_ec0fd5bd_fk_accounts_
FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importartifactmanifest
DROP CONSTRAINT IF EXISTS imports_importartifa_chunk_id_4a98caa1_fk_imports_i;
ALTER TABLE imports_importartifactmanifest
ADD CONSTRAINT imports_importartifa_chunk_id_4a98caa1_fk_imports_i
FOREIGN KEY (chunk_id) REFERENCES imports_importchunk(id)
ON DELETE CASCADE
DEFERRABLE INITIALLY DEFERRED;
"""


REVERSE_SQL = """
ALTER TABLE imports_importartifactmanifest
DROP CONSTRAINT IF EXISTS imports_importartifa_chunk_id_4a98caa1_fk_imports_i;
ALTER TABLE imports_importartifactmanifest
ADD CONSTRAINT imports_importartifa_chunk_id_4a98caa1_fk_imports_i
FOREIGN KEY (chunk_id) REFERENCES imports_importchunk(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importartifactmanifest
DROP CONSTRAINT IF EXISTS imports_importartifa_agency_id_ec0fd5bd_fk_accounts_;
ALTER TABLE imports_importartifactmanifest
ADD CONSTRAINT imports_importartifa_agency_id_ec0fd5bd_fk_accounts_
FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importartifactmanifest
DROP CONSTRAINT IF EXISTS imports_importartifa_job_id_9acce294_fk_imports_i;
ALTER TABLE imports_importartifactmanifest
ADD CONSTRAINT imports_importartifa_job_id_9acce294_fk_imports_i
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importchunkphase
DROP CONSTRAINT IF EXISTS imports_importchunkp_chunk_id_e6c7877a_fk_imports_i;
ALTER TABLE imports_importchunkphase
ADD CONSTRAINT imports_importchunkp_chunk_id_e6c7877a_fk_imports_i
FOREIGN KEY (chunk_id) REFERENCES imports_importchunk(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importchunk
DROP CONSTRAINT IF EXISTS imports_importchunk_agency_id_24f93a59_fk_accounts_agency_id;
ALTER TABLE imports_importchunk
ADD CONSTRAINT imports_importchunk_agency_id_24f93a59_fk_accounts_agency_id
FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importchunk
DROP CONSTRAINT IF EXISTS imports_importchunk_job_id_ff1859ae_fk_imports_importjob_id;
ALTER TABLE imports_importchunk
ADD CONSTRAINT imports_importchunk_job_id_ff1859ae_fk_imports_importjob_id
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importrowaudit
DROP CONSTRAINT IF EXISTS imports_importrowaudit_actor_id_98390f30_fk_accounts_user_id;
ALTER TABLE imports_importrowaudit
ADD CONSTRAINT imports_importrowaudit_actor_id_98390f30_fk_accounts_user_id
FOREIGN KEY (actor_id) REFERENCES accounts_user(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importrowaudit
DROP CONSTRAINT IF EXISTS imports_importrowaudit_agency_id_b2e4ddf8_fk_accounts_agency_id;
ALTER TABLE imports_importrowaudit
ADD CONSTRAINT imports_importrowaudit_agency_id_b2e4ddf8_fk_accounts_agency_id
FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importrowaudit
DROP CONSTRAINT IF EXISTS imports_importrowaudit_job_id_a2a95616_fk_imports_importjob_id;
ALTER TABLE imports_importrowaudit
ADD CONSTRAINT imports_importrowaudit_job_id_a2a95616_fk_imports_importjob_id
FOREIGN KEY (job_id) REFERENCES imports_importjob(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importjob
DROP CONSTRAINT IF EXISTS imports_importjob_agency_id_08860415_fk_accounts_agency_id;
ALTER TABLE imports_importjob
ADD CONSTRAINT imports_importjob_agency_id_08860415_fk_accounts_agency_id
FOREIGN KEY (agency_id) REFERENCES accounts_agency(id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE imports_importjob
DROP CONSTRAINT IF EXISTS imports_importjob_user_id_2e56696d_fk_accounts_user_id;
ALTER TABLE imports_importjob
ADD CONSTRAINT imports_importjob_user_id_2e56696d_fk_accounts_user_id
FOREIGN KEY (user_id) REFERENCES accounts_user(id)
DEFERRABLE INITIALLY DEFERRED;
"""


def _run_admin_sql(*, schema_editor: BaseDatabaseSchemaEditor, sql: str) -> None:
    settings_dict = schema_editor.connection.settings_dict
    connection_kwargs = {
        "dbname": settings_dict["NAME"],
        "user": os.environ.get("POSTGRES_ADMIN_USER") or settings_dict.get("USER") or "",
        "password": os.environ.get("POSTGRES_ADMIN_PASSWORD")
        or settings_dict.get("PASSWORD")
        or "",
        "host": settings_dict.get("HOST") or "",
        "port": str(settings_dict.get("PORT") or "5432"),
    }
    with psycopg.connect(**connection_kwargs) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
        conn.commit()


def apply_forward_fk_cascade_contract(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    del apps
    _run_admin_sql(schema_editor=schema_editor, sql=FORWARD_SQL)


def apply_reverse_fk_cascade_contract(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    del apps
    _run_admin_sql(schema_editor=schema_editor, sql=REVERSE_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0008_importagencyprofile_importdeadletterrow"),
    ]

    operations = [
        migrations.RunPython(
            code=apply_forward_fk_cascade_contract,
            reverse_code=apply_reverse_fk_cascade_contract,
        ),
    ]
