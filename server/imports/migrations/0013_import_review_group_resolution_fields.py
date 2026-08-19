from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0012_import_review_fk_cascade_enforce_current_connection"),
    ]

    operations = [
        migrations.AddField(
            model_name="importreviewgroup",
            name="apply_to_all_allowed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="importreviewgroup",
            name="apply_to_all_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="importreviewgroup",
            name="consistent_existing_id",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="importreviewgroup",
            name="resolution_template",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="importreviewgroup",
            name="resolved_item_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="importreviewitem",
            name="group_resolvable",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="importreviewitem",
            name="group_resolution_blockers",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="importreviewitem",
            name="resolution_source",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="importreviewitem",
            name="root_identity_snapshot",
            field=models.JSONField(default=dict),
        ),
    ]
