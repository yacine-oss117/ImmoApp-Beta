import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_add_import_permission"),
    ]

    operations = [
        migrations.CreateModel(
            name="DiagnosticsEnrollmentToken",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("token_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("device_id", models.CharField(blank=True, max_length=128)),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="diagnostics_enrollment_tokens",
                        to="accounts.agency",
                    ),
                ),
                (
                    "consumed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="diagnostics_tokens_consumed",
                        to="accounts.user",
                    ),
                ),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="diagnostics_tokens_issued",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=("agency", "expires_at"), name="acct_diag_tok_exp_idx"),
                    models.Index(fields=("agency", "consumed_at"), name="acct_diag_tok_use_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DiagnosticsSigningKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("device_id", models.CharField(max_length=128)),
                ("signature_key_id", models.CharField(max_length=128)),
                ("public_key", models.TextField()),
                ("is_active", models.BooleanField(default=True)),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="diagnostics_keys",
                        to="accounts.agency",
                    ),
                ),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="diagnostics_keys_approved",
                        to="accounts.user",
                    ),
                ),
                (
                    "enrolled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="diagnostics_keys_enrolled",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=("agency", "device_id", "is_active"),
                        name="acct_diag_key_act_idx",
                    ),
                    models.Index(
                        fields=("agency", "signature_key_id"),
                        name="acct_diag_key_sig_idx",
                    ),
                ],
                "unique_together": {("agency", "device_id", "signature_key_id")},
            },
        ),
    ]
