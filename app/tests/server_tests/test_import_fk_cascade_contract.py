from __future__ import annotations

from app.tests.server_tests._integration_auth_helpers import admin_conn, ensure_django

ensure_django()

EXPECTED_IMPORT_CASCADE_CONSTRAINTS = {
    "imports_importjob_user_id_2e56696d_fk_accounts_user_id": "ON DELETE CASCADE",
    "imports_importjob_agency_id_08860415_fk_accounts_agency_id": "ON DELETE CASCADE",
    "imports_importrowaudit_job_id_a2a95616_fk_imports_importjob_id": "ON DELETE CASCADE",
    "imports_importrowaudit_agency_id_b2e4ddf8_fk_accounts_agency_id": "ON DELETE CASCADE",
    "imports_importrowaudit_actor_id_98390f30_fk_accounts_user_id": "ON DELETE CASCADE",
    "imports_importchunk_job_id_ff1859ae_fk_imports_importjob_id": "ON DELETE CASCADE",
    "imports_importchunk_agency_id_24f93a59_fk_accounts_agency_id": "ON DELETE CASCADE",
    "imports_importchunkp_chunk_id_e6c7877a_fk_imports_i": "ON DELETE CASCADE",
    "imports_importartifa_job_id_9acce294_fk_imports_i": "ON DELETE CASCADE",
    "imports_importartifa_agency_id_ec0fd5bd_fk_accounts_": "ON DELETE CASCADE",
    "imports_importartifa_chunk_id_4a98caa1_fk_imports_i": "ON DELETE CASCADE",
    "imports_irgrp_job_fk_impjob": "ON DELETE CASCADE",
    "imports_iritm_job_fk_impjob": "ON DELETE CASCADE",
    "imports_iritm_group_fk_irgrp": "ON DELETE CASCADE",
}


def test_import_schema_enforces_db_level_cascade_for_runtime_cleanup_paths() -> None:
    conn = admin_conn()
    try:
        rows = conn.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = ANY(%s)
            """,
            [list(EXPECTED_IMPORT_CASCADE_CONSTRAINTS.keys())],
        ).fetchall()
    finally:
        conn.close()

    found = {str(row["conname"]): str(row["pg_get_constraintdef"]) for row in rows}
    assert found.keys() == EXPECTED_IMPORT_CASCADE_CONSTRAINTS.keys()
    for constraint_name, required_fragment in EXPECTED_IMPORT_CASCADE_CONSTRAINTS.items():
        assert required_fragment in found[constraint_name], (
            constraint_name,
            found[constraint_name],
        )
