from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0015_email_outbox"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="user",
            index=models.Index(
                fields=("agency", "is_active", "id"),
                name="acct_user_ag_act_id_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(
                fields=("agency", "role", "is_active", "id"),
                name="acct_user_ag_role_act_id_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="userinvite",
            index=models.Index(
                fields=("agency", "status", "created_at", "id"),
                name="acct_inv_page_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="userinvite",
            index=models.Index(
                fields=("agency", "status", "manager", "created_at", "id"),
                name="acct_inv_mgr_page_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="userinvite",
            index=models.Index(
                fields=("agency", "status", "invited_by", "created_at", "id"),
                name="acct_inv_ib_page_idx",
            ),
        ),
    ]
