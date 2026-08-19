from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0009_import_fk_cascade_contract"),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportReviewGroup",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("group_key", models.CharField(max_length=128)),
                (
                    "group_kind",
                    models.CharField(
                        choices=[
                            ("bundle_root", "Bundle Root"),
                            ("single_row", "Single Row"),
                            ("duplicate_conflict", "Duplicate Conflict"),
                            ("field_conflict", "Field Conflict"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("partially_resolved", "Partially Resolved"),
                            ("resolved", "Resolved"),
                            ("blocked", "Blocked"),
                        ],
                        default="pending",
                        max_length=24,
                    ),
                ),
                ("issue_group", models.CharField(blank=True, default="", max_length=64)),
                ("issue_title", models.CharField(blank=True, default="", max_length=255)),
                ("issue_summary", models.TextField(blank=True, default="")),
                ("entity_type", models.CharField(blank=True, default="", max_length=50)),
                ("topology_side", models.CharField(blank=True, default="", max_length=32)),
                ("root_identity", models.JSONField(default=dict)),
                ("root_label", models.CharField(blank=True, default="", max_length=255)),
                ("root_row_ordinal", models.IntegerField(default=0)),
                ("item_count", models.IntegerField(default=0)),
                ("pending_item_count", models.IntegerField(default=0)),
                ("blocking_item_count", models.IntegerField(default=0)),
                ("suggested_group_action", models.CharField(blank=True, default="", max_length=32)),
                ("search_text", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="review_groups",
                        to="imports.importjob",
                    ),
                ),
            ],
            options={
                "ordering": ["job_id", "root_row_ordinal", "group_key"],
            },
        ),
        migrations.CreateModel(
            name="ImportReviewItem",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("row_ordinal", models.IntegerField()),
                ("entity_type", models.CharField(max_length=50)),
                ("topology_side", models.CharField(blank=True, default="", max_length=32)),
                ("issue_group", models.CharField(blank=True, default="", max_length=64)),
                ("issue_title", models.CharField(blank=True, default="", max_length=255)),
                ("issue_summary", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("resolved", "Resolved"),
                            ("skipped", "Skipped"),
                            ("blocked", "Blocked"),
                        ],
                        default="pending",
                        max_length=24,
                    ),
                ),
                ("blocking", models.BooleanField(default=False)),
                ("immutable_conflict", models.BooleanField(default=False)),
                ("suggested_action", models.CharField(blank=True, default="", max_length=32)),
                ("suggested_existing_id", models.BigIntegerField(default=0)),
                ("suggested_confidence", models.FloatField(default=0.0)),
                ("recoverability_class", models.CharField(blank=True, default="", max_length=64)),
                ("raw_data", models.JSONField(default=dict)),
                ("normalized_data", models.JSONField(default=dict)),
                ("review_fields", models.JSONField(default=list)),
                ("candidate_matches", models.JSONField(default=list)),
                ("recovered_fields", models.JSONField(default=list)),
                ("recovery_candidates", models.JSONField(default=list)),
                ("blocking_reasons", models.JSONField(default=list)),
                ("quick_fix_actions", models.JSONField(default=list)),
                ("bulk_fix_groups", models.JSONField(default=list)),
                ("resolution", models.JSONField(default=dict)),
                ("metadata", models.JSONField(default=dict)),
                ("search_text", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="imports.importreviewgroup",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="review_items",
                        to="imports.importjob",
                    ),
                ),
            ],
            options={
                "ordering": ["job_id", "row_ordinal", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="importreviewgroup",
            constraint=models.UniqueConstraint(
                fields=("job", "group_key"),
                name="uq_import_review_group_job_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="importreviewitem",
            constraint=models.UniqueConstraint(
                fields=("job", "row_ordinal", "entity_type", "group"),
                name="uq_import_review_item_job_row_entity_group",
            ),
        ),
        migrations.AddIndex(
            model_name="importreviewgroup",
            index=models.Index(
                fields=["job", "status"],
                name="idx_imp_rgrp_job_sts",
            ),
        ),
        migrations.AddIndex(
            model_name="importreviewgroup",
            index=models.Index(
                fields=["job", "issue_group", "status"],
                name="idx_imp_rgrp_job_issue_st",
            ),
        ),
        migrations.AddIndex(
            model_name="importreviewgroup",
            index=models.Index(
                fields=["job", "entity_type", "status"],
                name="idx_imp_rgrp_job_entity_st",
            ),
        ),
        migrations.AddIndex(
            model_name="importreviewitem",
            index=models.Index(
                fields=["job", "status"],
                name="idx_imp_ritem_job_sts",
            ),
        ),
        migrations.AddIndex(
            model_name="importreviewitem",
            index=models.Index(
                fields=["job", "group", "status"],
                name="idx_imp_ritem_job_grp",
            ),
        ),
        migrations.AddIndex(
            model_name="importreviewitem",
            index=models.Index(
                fields=["job", "row_ordinal"],
                name="idx_imp_ritem_job_row",
            ),
        ),
        migrations.AddIndex(
            model_name="importreviewitem",
            index=models.Index(
                fields=["job", "issue_group", "status"],
                name="idx_imp_ritem_job_issue_st",
            ),
        ),
    ]
