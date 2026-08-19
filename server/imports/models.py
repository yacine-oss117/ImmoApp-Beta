import uuid

from django.db import models


class ImportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        PARSING = "parsing"
        READY = "ready"
        QUEUED = "queued"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"

    class Stage(models.TextChoices):
        UPLOAD = "upload"
        MAPPING = "mapping"
        REVIEW = "review"
        EXECUTION = "execution"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="import_jobs")
    agency = models.ForeignKey(
        "accounts.Agency", on_delete=models.CASCADE, related_name="import_jobs"
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.UPLOAD)
    progress = models.IntegerField(default=0)

    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10)  # csv, excel, ods
    source_path = models.CharField(max_length=1024, null=True, blank=True)

    ui_entity_hint = models.CharField(max_length=50, null=True, blank=True)
    detected_entity = models.CharField(max_length=50, null=True, blank=True)
    detected_columns = models.JSONField(default=list)
    column_mapping = models.JSONField(default=dict)
    preview_rows = models.JSONField(default=list)

    inference_summary = models.JSONField(default=dict)
    progress_detail = models.JSONField(default=dict)
    result_summary = models.JSONField(default=dict)
    review_rows = models.JSONField(default=list)
    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    task_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"], name="idx_import_jobs_user_status"),
            models.Index(fields=["agency", "created_at"], name="idx_import_jobs_agency_created"),
        ]

    def __str__(self) -> str:
        return f"Import {self.filename} ({self.status})"


class ImportWorkflowState(models.Model):
    job = models.OneToOneField(
        "imports.ImportJob",
        on_delete=models.CASCADE,
        related_name="workflow_state",
    )
    run_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=20, blank=True, default="")
    fingerprint = models.CharField(max_length=128, blank=True, default="")
    cancel_requested = models.BooleanField(default=False)
    prepare_completed = models.BooleanField(default=False)
    finalize_queued = models.BooleanField(default=False)
    finalized = models.BooleanField(default=False)
    queue_position = models.IntegerField(default=0)
    queued_at = models.DateTimeField(null=True, blank=True)
    execution_profile = models.CharField(max_length=20, blank=True, default="")
    admission_mode = models.CharField(max_length=20, blank=True, default="")
    pressure_reason = models.CharField(max_length=64, blank=True, default="")
    bundle_mode = models.CharField(max_length=32, blank=True, default="")
    topology_side = models.CharField(max_length=32, blank=True, default="")
    params = models.JSONField(default=dict)
    prepare_counts = models.JSONField(default=dict)
    load_counts = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    root_plan_index_ready = models.BooleanField(default=False)
    root_plan_index_manifest_id = models.BigIntegerField(default=0)
    root_plan_index_checksum = models.CharField(max_length=64, blank=True, default="")
    root_plan_index_key_count = models.IntegerField(default=0)
    root_load_anchor_map_ready = models.BooleanField(default=False)
    root_load_anchor_map_manifest_id = models.BigIntegerField(default=0)
    root_load_anchor_map_checksum = models.CharField(max_length=64, blank=True, default="")
    root_load_anchor_map_key_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["job_id"]
        indexes = [
            models.Index(fields=["status", "queued_at"], name="idx_imp_wf_status_queue"),
            models.Index(fields=["execution_profile"], name="idx_imp_wf_exec_profile"),
        ]

    def __str__(self) -> str:
        return f"ImportWorkflowState(job={self.job_id}, status={self.status})"


class ImportAgencyAlias(models.Model):
    class Domain(models.TextChoices):
        LOCATION = "location"
        PROPERTY_TYPE = "property_type"
        ACTION = "action"
        HEADER = "header"

    class State(models.TextChoices):
        SHADOW = "shadow"
        TRUSTED = "trusted"
        REJECTED = "rejected"

    id = models.BigAutoField(primary_key=True)
    agency = models.ForeignKey(
        "accounts.Agency",
        on_delete=models.CASCADE,
        related_name="import_agency_aliases",
    )
    domain = models.CharField(max_length=32, choices=Domain.choices)
    source_value_original = models.TextField(blank=True, default="")
    source_value_normalized = models.CharField(max_length=255)
    canonical_key = models.CharField(max_length=255, blank=True, default="")
    canonical_label = models.CharField(max_length=255, blank=True, default="")
    state = models.CharField(max_length=20, choices=State.choices, default=State.SHADOW)
    confirm_count = models.IntegerField(default=0)
    reject_count = models.IntegerField(default=0)
    distinct_job_count = models.IntegerField(default=0)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    last_job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.SET_NULL,
        related_name="agency_alias_updates",
        null=True,
        blank=True,
    )
    last_actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="agency_alias_updates",
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["agency_id", "domain", "source_value_normalized"]
        constraints = [
            models.UniqueConstraint(
                fields=["agency", "domain", "source_value_normalized"],
                name="uq_import_agency_alias_source",
            )
        ]
        indexes = [
            models.Index(fields=["agency", "domain", "state"], name="idx_imp_alias_ag_dom_state"),
            models.Index(
                fields=["agency", "source_value_normalized"],
                name="idx_imp_alias_ag_source",
            ),
        ]

    def __str__(self) -> str:
        return (
            "ImportAgencyAlias("
            f"agency={self.agency_id}, domain={self.domain}, source={self.source_value_normalized})"
        )


class ImportCorrectionSignal(models.Model):
    id = models.BigAutoField(primary_key=True)
    agency = models.ForeignKey(
        "accounts.Agency",
        on_delete=models.CASCADE,
        related_name="import_correction_signals",
    )
    job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.CASCADE,
        related_name="correction_signals",
    )
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="import_correction_signals",
        null=True,
        blank=True,
    )
    row_ordinal = models.IntegerField()
    entity_type = models.CharField(max_length=50)
    field_name = models.CharField(max_length=100)
    domain = models.CharField(max_length=32)
    source_value_original = models.TextField(blank=True, default="")
    source_value_normalized = models.CharField(max_length=255, blank=True, default="")
    corrected_value_original = models.TextField(blank=True, default="")
    corrected_value_normalized = models.CharField(max_length=255, blank=True, default="")
    canonical_key = models.CharField(max_length=255, blank=True, default="")
    canonical_label = models.CharField(max_length=255, blank=True, default="")
    decision_action = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["agency", "domain", "source_value_normalized"],
                name="idx_imp_corrsig_ag_dom_src",
            ),
            models.Index(
                fields=["agency", "field_name", "created_at"],
                name="idx_imp_corrsig_ag_field_ct",
            ),
            models.Index(fields=["job", "row_ordinal"], name="idx_imp_corrsig_job_row"),
        ]

    def __str__(self) -> str:
        return (
            "ImportCorrectionSignal("
            f"job={self.job_id}, row={self.row_ordinal}, field={self.field_name})"
        )


class ImportAgencyProfile(models.Model):
    agency = models.OneToOneField(
        "accounts.Agency",
        on_delete=models.CASCADE,
        related_name="import_agency_profile",
        primary_key=True,
    )
    memory_version = models.CharField(max_length=64, blank=True, default="")
    preferred_language = models.CharField(max_length=16, blank=True, default="")
    default_wilaya_code = models.CharField(max_length=8, blank=True, default="")
    common_bundle_shape = models.CharField(max_length=64, blank=True, default="")
    property_vocab = models.JSONField(default=dict)
    location_abbreviations = models.JSONField(default=dict)
    action_vocab = models.JSONField(default=dict)
    header_vocab = models.JSONField(default=dict)
    common_missing_fields = models.JSONField(default=list)
    last_imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["agency_id"]

    def __str__(self) -> str:
        return f"ImportAgencyProfile(agency={self.agency_id})"


class ImportDeadLetterRow(models.Model):
    class Disposition(models.TextChoices):
        AUTO_SKIPPED = "auto_skipped"
        HUMAN_SKIPPED = "human_skipped"
        BLOCKING_DISCARDED = "blocking_discarded"

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.CASCADE,
        related_name="dead_letter_rows",
    )
    agency = models.ForeignKey(
        "accounts.Agency",
        on_delete=models.CASCADE,
        related_name="import_dead_letter_rows",
    )
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="import_dead_letter_rows",
        null=True,
        blank=True,
    )
    row_ordinal = models.IntegerField()
    entity_type = models.CharField(max_length=50, blank=True, default="")
    topology_side = models.CharField(max_length=32, blank=True, default="")
    disposition = models.CharField(max_length=32, choices=Disposition.choices)
    phase = models.CharField(max_length=32, blank=True, default="")
    reason_codes = models.JSONField(default=list)
    reason_messages = models.JSONField(default=list)
    raw_data = models.JSONField(default=dict)
    normalized_data = models.JSONField(default=dict)
    recoverability_class = models.CharField(max_length=32, blank=True, default="")
    recovered_fields = models.JSONField(default=list)
    recovery_candidates = models.JSONField(default=list)
    blocking_reasons = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["agency", "created_at"], name="idx_imp_dead_ag_created"),
            models.Index(fields=["job", "row_ordinal"], name="idx_imp_dead_job_row"),
            models.Index(
                fields=["agency", "disposition", "created_at"],
                name="idx_imp_dead_ag_disp_ct",
            ),
        ]

    def __str__(self) -> str:
        return (
            "ImportDeadLetterRow("
            f"job={self.job_id}, row={self.row_ordinal}, disposition={self.disposition})"
        )


class ImportReviewGroup(models.Model):
    class Kind(models.TextChoices):
        BUNDLE_ROOT = "bundle_root"
        SINGLE_ROW = "single_row"
        DUPLICATE_CONFLICT = "duplicate_conflict"
        FIELD_CONFLICT = "field_conflict"

    class Status(models.TextChoices):
        PENDING = "pending"
        PARTIALLY_RESOLVED = "partially_resolved"
        RESOLVED = "resolved"
        BLOCKED = "blocked"

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.CASCADE,
        related_name="review_groups",
    )
    group_key = models.CharField(max_length=128)
    group_kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    issue_group = models.CharField(max_length=64, blank=True, default="")
    issue_title = models.CharField(max_length=255, blank=True, default="")
    issue_summary = models.TextField(blank=True, default="")
    entity_type = models.CharField(max_length=50, blank=True, default="")
    topology_side = models.CharField(max_length=32, blank=True, default="")
    root_identity = models.JSONField(default=dict)
    root_label = models.CharField(max_length=255, blank=True, default="")
    root_row_ordinal = models.IntegerField(default=0)
    item_count = models.IntegerField(default=0)
    pending_item_count = models.IntegerField(default=0)
    blocking_item_count = models.IntegerField(default=0)
    suggested_group_action = models.CharField(max_length=32, blank=True, default="")
    apply_to_all_allowed = models.BooleanField(default=False)
    apply_to_all_count = models.IntegerField(default=0)
    consistent_existing_id = models.BigIntegerField(default=0)
    resolution_template = models.JSONField(default=dict)
    resolved_item_count = models.IntegerField(default=0)
    search_text = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["job_id", "root_row_ordinal", "group_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "group_key"],
                name="uq_import_review_group_job_key",
            )
        ]
        indexes = [
            models.Index(fields=["job", "status"], name="idx_imp_rgrp_job_sts"),
            models.Index(
                fields=["job", "issue_group", "status"],
                name="idx_imp_rgrp_job_issue_st",
            ),
            models.Index(
                fields=["job", "entity_type", "status"],
                name="idx_imp_rgrp_job_entity_st",
            ),
        ]

    def __str__(self) -> str:
        return (
            "ImportReviewGroup(" f"job={self.job_id}, key={self.group_key}, status={self.status})"
        )


class ImportReviewItem(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        RESOLVED = "resolved"
        SKIPPED = "skipped"
        BLOCKED = "blocked"

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.CASCADE,
        related_name="review_items",
    )
    group = models.ForeignKey(
        "imports.ImportReviewGroup",
        on_delete=models.CASCADE,
        related_name="items",
    )
    row_ordinal = models.IntegerField()
    entity_type = models.CharField(max_length=50)
    topology_side = models.CharField(max_length=32, blank=True, default="")
    issue_group = models.CharField(max_length=64, blank=True, default="")
    issue_title = models.CharField(max_length=255, blank=True, default="")
    issue_summary = models.TextField(blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    blocking = models.BooleanField(default=False)
    immutable_conflict = models.BooleanField(default=False)
    suggested_action = models.CharField(max_length=32, blank=True, default="")
    suggested_existing_id = models.BigIntegerField(default=0)
    suggested_confidence = models.FloatField(default=0.0)
    recoverability_class = models.CharField(max_length=64, blank=True, default="")
    raw_data = models.JSONField(default=dict)
    normalized_data = models.JSONField(default=dict)
    review_fields = models.JSONField(default=list)
    candidate_matches = models.JSONField(default=list)
    recovered_fields = models.JSONField(default=list)
    recovery_candidates = models.JSONField(default=list)
    blocking_reasons = models.JSONField(default=list)
    quick_fix_actions = models.JSONField(default=list)
    bulk_fix_groups = models.JSONField(default=list)
    resolution = models.JSONField(default=dict)
    group_resolvable = models.BooleanField(default=False)
    group_resolution_blockers = models.JSONField(default=list)
    resolution_source = models.CharField(max_length=16, blank=True, default="")
    root_identity_snapshot = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    search_text = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["job_id", "row_ordinal", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "row_ordinal", "entity_type", "group"],
                name="uq_import_review_item_job_row_entity_group",
            )
        ]
        indexes = [
            models.Index(fields=["job", "status"], name="idx_imp_ritem_job_sts"),
            models.Index(fields=["job", "group", "status"], name="idx_imp_ritem_job_grp"),
            models.Index(fields=["job", "row_ordinal"], name="idx_imp_ritem_job_row"),
            models.Index(
                fields=["job", "issue_group", "status"],
                name="idx_imp_ritem_job_issue_st",
            ),
        ]

    def __str__(self) -> str:
        return (
            "ImportReviewItem(" f"job={self.job_id}, row={self.row_ordinal}, status={self.status})"
        )


class ImportRowAudit(models.Model):
    class Action(models.TextChoices):
        CREATE = "create"
        UPDATE = "update"
        REVIEW = "review"
        SKIP = "skip"

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.CASCADE,
        related_name="row_audits",
    )
    agency = models.ForeignKey(
        "accounts.Agency",
        on_delete=models.CASCADE,
        related_name="import_row_audits",
    )
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="import_row_audits",
    )
    row_ordinal = models.IntegerField()
    entity_type = models.CharField(max_length=50)
    action = models.CharField(max_length=20, choices=Action.choices)
    target_table = models.CharField(max_length=100, blank=True, default="")
    target_id = models.IntegerField(default=0)
    target_row_version = models.IntegerField(default=0)
    before_payload = models.JSONField(default=dict)
    after_payload = models.JSONField(default=dict)
    diff_payload = models.JSONField(default=dict)
    reasons = models.JSONField(default=list)
    correction_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["job", "row_ordinal"], name="idx_imp_audit_job_row"),
            models.Index(fields=["agency", "created_at"], name="idx_imp_audit_agency_created"),
        ]

    def __str__(self) -> str:
        return f"ImportRowAudit(job={self.job_id}, row={self.row_ordinal}, action={self.action})"


class ImportChunk(models.Model):
    class Role(models.TextChoices):
        SINGLE = "single"
        ROOT = "root"
        CHILD = "child"

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    agency = models.ForeignKey(
        "accounts.Agency",
        on_delete=models.CASCADE,
        related_name="import_chunks",
    )
    ordinal = models.IntegerField()
    chunk_role = models.CharField(max_length=20, choices=Role.choices, default=Role.SINGLE)
    entity_type = models.CharField(max_length=50, blank=True, default="")
    row_start = models.IntegerField(default=0)
    row_end = models.IntegerField(default=0)
    row_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["job_id", "ordinal", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "ordinal", "chunk_role"],
                name="uq_import_chunk_job_ord_role",
            ),
        ]
        indexes = [
            models.Index(fields=["job", "chunk_role"], name="idx_imp_chunk_job_role"),
            models.Index(fields=["agency", "created_at"], name="idx_imp_chunk_agency_created"),
        ]

    def __str__(self) -> str:
        return f"ImportChunk(job={self.job_id}, role={self.chunk_role}, ordinal={self.ordinal})"


class ImportChunkPhase(models.Model):
    class Phase(models.TextChoices):
        PLAN = "plan"
        LOAD = "load"

    class Status(models.TextChoices):
        BLOCKED = "blocked"
        PENDING = "pending"
        QUEUED = "queued"
        RUNNING = "running"
        CANCELLED = "cancelled"
        COMPLETED = "completed"
        FAILED = "failed"

    id = models.BigAutoField(primary_key=True)
    chunk = models.ForeignKey(
        "imports.ImportChunk",
        on_delete=models.CASCADE,
        related_name="phases",
    )
    phase = models.CharField(max_length=20, choices=Phase.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempt_count = models.IntegerField(default=0)
    task_id = models.CharField(max_length=255, blank=True, default="")
    lease_token = models.CharField(max_length=64, blank=True, default="")
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_payload = models.JSONField(default=dict)
    metrics_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chunk_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["chunk", "phase"],
                name="uq_import_chunk_phase",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "phase"], name="idx_imp_chunk_phase_status"),
            models.Index(fields=["chunk", "status"], name="idx_imp_cphase_chunk_stat"),
        ]

    def __str__(self) -> str:
        return f"ImportChunkPhase(chunk={self.chunk_id}, phase={self.phase}, status={self.status})"


class ImportArtifactManifest(models.Model):
    class Phase(models.TextChoices):
        PREPARE = "prepare"
        PLAN = "plan"
        LOAD = "load"
        FINALIZE = "finalize"

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.CASCADE,
        related_name="artifact_manifests",
    )
    agency = models.ForeignKey(
        "accounts.Agency",
        on_delete=models.CASCADE,
        related_name="import_artifact_manifests",
    )
    chunk = models.ForeignKey(
        "imports.ImportChunk",
        on_delete=models.CASCADE,
        related_name="artifact_manifests",
        null=True,
        blank=True,
    )
    phase = models.CharField(max_length=20, choices=Phase.choices)
    artifact_kind = models.CharField(max_length=50)
    storage_id = models.CharField(max_length=255)
    checksum = models.CharField(max_length=64, blank=True, default="")
    row_count = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["job_id", "chunk_id", "id"]
        indexes = [
            models.Index(fields=["job", "phase"], name="idx_imp_art_job_phase"),
            models.Index(fields=["chunk", "artifact_kind"], name="idx_imp_art_chunk_kind"),
            models.Index(fields=["agency", "created_at"], name="idx_imp_art_agency_created"),
        ]

    def __str__(self) -> str:
        return (
            "ImportArtifactManifest("
            f"job={self.job_id}, chunk={self.chunk_id}, kind={self.artifact_kind})"
        )
