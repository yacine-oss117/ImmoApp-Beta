from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Agency(models.Model):
    """Agency is the tenant boundary for all business data."""

    legal_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    agency_code = models.CharField(max_length=64, unique=True)
    kbis_number = models.CharField(max_length=128, blank=True)
    phone_number = models.CharField(max_length=64, blank=True)
    phone_number_enc = models.TextField(blank=True, default="")
    email = models.EmailField(blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line1_enc = models.TextField(blank=True, default="")
    address_line2 = models.CharField(max_length=255, blank=True)
    address_line2_enc = models.TextField(blank=True, default="")
    city = models.CharField(max_length=128, blank=True)
    city_enc = models.TextField(blank=True, default="")
    postal_code = models.CharField(max_length=32, blank=True)
    country = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=True)
    max_users = models.PositiveIntegerField(default=3)
    max_managers = models.PositiveIntegerField(default=1)
    max_agents_per_manager = models.PositiveIntegerField(default=2)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_name", "id")

    def __str__(self) -> str:
        return f"{self.display_name} ({self.agency_code})"


class User(AbstractUser):
    """Custom user with agency role and visibility scope."""

    ROLE_SUPER_ADMIN = "super_admin"
    ROLE_MANAGER = "manager"
    ROLE_AGENT = "agent"
    ROLE_CHOICES = (
        (ROLE_SUPER_ADMIN, "Super Admin"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_AGENT, "Agent"),
    )

    SCOPE_OWN = "own"
    SCOPE_AGENCY = "agency"
    ACCESS_SCOPE_CHOICES = (
        (SCOPE_OWN, "Own"),
        (SCOPE_AGENCY, "Agency"),
    )

    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_AGENT)
    agency = models.ForeignKey(
        Agency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agents",
    )
    access_scope = models.CharField(max_length=32, choices=ACCESS_SCOPE_CHOICES, default=SCOPE_OWN)
    is_owner = models.BooleanField(default=False)
    can_hard_delete = models.BooleanField(default=False)
    can_import = models.BooleanField(default=False)
    import_granted_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_grantees",
        help_text="The manager who granted import permission to this agent.",
    )
    timezone = models.CharField(max_length=64, blank=True)
    locale = models.CharField(max_length=32, blank=True)
    first_name_enc = models.TextField(blank=True, default="")
    last_name_enc = models.TextField(blank=True, default="")
    first_name_search_src = models.CharField(max_length=255, blank=True, default="")
    last_name_search_src = models.CharField(max_length=255, blank=True, default="")
    mfa_totp_enabled = models.BooleanField(default=False)
    mfa_totp_secret = models.CharField(max_length=128, blank=True)
    mfa_totp_secret_enc = models.TextField(blank=True, default="")
    mfa_totp_enrolled_at = models.DateTimeField(null=True, blank=True)
    session_invalid_before = models.DateTimeField(null=True, blank=True)

    class Meta(AbstractUser.Meta):
        indexes = [
            models.Index(
                fields=("agency", "is_active", "id"),
                name="acct_user_ag_act_id_idx",
            ),
            models.Index(
                fields=("agency", "role", "is_active", "id"),
                name="acct_user_ag_role_act_id_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()

        if self.role == self.ROLE_SUPER_ADMIN and not self.is_superuser:
            raise ValidationError({"role": "Super admin role requires the user to be a superuser."})
        if self.is_superuser:
            return

        if not self.agency_id:
            raise ValidationError({"agency": "Agency is required for non-super_admin users."})

        if self.role == self.ROLE_MANAGER:
            if self.manager_id:
                raise ValidationError({"manager": "Managers cannot have a manager."})
        else:
            if not self.manager_id:
                raise ValidationError({"manager": "Agents must have a manager."})
            if self.manager_id == self.pk:
                raise ValidationError({"manager": "Users cannot manage themselves."})
            if self.manager and self.manager.role != self.ROLE_MANAGER:
                raise ValidationError({"manager": "Agent manager must be a manager user."})
            if self.manager and self.manager.agency_id != self.agency_id:
                raise ValidationError({"manager": "Agent manager must belong to the same agency."})
            if self.manager and not self.manager.is_active:
                raise ValidationError({"manager": "Agent manager must be active."})

        if self.can_hard_delete and self.role != self.ROLE_MANAGER:
            raise ValidationError(
                {"can_hard_delete": "Only managers can be granted hard delete access."}
            )

        if self.is_owner and self.role != self.ROLE_MANAGER:
            raise ValidationError({"is_owner": "Only managers can be agency owners."})
        if self.is_owner and self.agency_id:
            owners_qs = self.__class__.objects.filter(
                agency=self.agency, role=self.ROLE_MANAGER, is_owner=True
            ).exclude(pk=self.pk)
            if owners_qs.exists():
                raise ValidationError({"is_owner": "Only one agency owner is allowed per agency."})

        # Import permission validation
        if self.can_import and self.role == self.ROLE_AGENT:
            # Agents with import permission must have a valid granter
            if not self.import_granted_by_id:
                raise ValidationError(
                    {"import_granted_by": "Agent import permission requires a granter."}
                )
            # Granter must be agent's manager or an agency owner
            granter = self.import_granted_by
            if granter and granter.role != self.ROLE_MANAGER:
                raise ValidationError(
                    {"import_granted_by": "Import permission must be granted by a manager."}
                )
            if granter and granter.agency_id != self.agency_id:
                raise ValidationError(
                    {"import_granted_by": "Granter must belong to the same agency."}
                )
        elif self.role == self.ROLE_MANAGER:
            # Managers always have import permission (no need for granter)
            self.import_granted_by = None

        if not self.is_active:
            return

        model = self.__class__
        base_qs = (
            model.objects.filter(agency=self.agency, is_active=True)
            .exclude(pk=self.pk)
            .exclude(role=self.ROLE_SUPER_ADMIN)
        )
        if base_qs.count() >= self.agency.max_users:
            raise ValidationError(
                {
                    "agency": (
                        f"Agency '{self.agency}' already has the maximum active users "
                        f"({self.agency.max_users})."
                    )
                }
            )

        if self.role == self.ROLE_MANAGER:
            managers_qs = base_qs.filter(role=self.ROLE_MANAGER)
            if managers_qs.count() >= self.agency.max_managers:
                raise ValidationError(
                    {
                        "role": (
                            f"Agency '{self.agency}' already has the maximum active managers "
                            f"({self.agency.max_managers})."
                        )
                    }
                )
        elif self.manager_id:
            agents_qs = model.objects.filter(
                manager=self.manager, role=self.ROLE_AGENT, is_active=True
            ).exclude(pk=self.pk)
            if agents_qs.count() >= self.agency.max_agents_per_manager:
                raise ValidationError(
                    {
                        "manager": (
                            f"Manager '{self.manager}' already has the maximum active agents "
                            f"({self.agency.max_agents_per_manager})."
                        )
                    }
                )

    def save(self, *args: object, **kwargs: object) -> None:
        validate = bool(kwargs.pop("validate", True))
        if self.is_superuser:
            self.role = self.ROLE_SUPER_ADMIN
            self.access_scope = self.SCOPE_AGENCY
            self.can_hard_delete = True
            self.manager = None
            self.agency = None
            self.is_owner = False
        elif self.role == self.ROLE_MANAGER:
            self.access_scope = self.SCOPE_AGENCY
        if validate:
            self.full_clean()
        super().save(*args, **kwargs)


class RegistrationRequest(models.Model):
    """Agency owner registration request pending manual platform review."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_BLACKLISTED = "blacklisted"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_BLACKLISTED, "Blacklisted"),
        (STATUS_EXPIRED, "Expired"),
    )

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)

    agency_name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255)
    registry_number = models.CharField(max_length=128)
    agency_address = models.CharField(max_length=500)
    agency_city = models.CharField(max_length=128)
    agency_postal_code = models.CharField(max_length=32)
    owner_first_name = models.CharField(max_length=100)
    owner_last_name = models.CharField(max_length=100)
    owner_phone = models.CharField(max_length=64)

    agency_name_enc = models.TextField(blank=True, default="")
    legal_name_enc = models.TextField(blank=True, default="")
    registry_number_enc = models.TextField(blank=True, default="")
    agency_address_enc = models.TextField(blank=True, default="")
    agency_city_enc = models.TextField(blank=True, default="")
    agency_postal_code_enc = models.TextField(blank=True, default="")
    owner_first_name_enc = models.TextField(blank=True, default="")
    owner_last_name_enc = models.TextField(blank=True, default="")
    owner_phone_enc = models.TextField(blank=True, default="")

    owner_email = models.EmailField(unique=True)
    terms_accepted = models.BooleanField(default=False)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)

    approval_token_hash = models.CharField(max_length=128, blank=True)
    activation_code_hash = models.CharField(max_length=128, blank=True)
    activation_code_expires_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("status", "created_at"), name="acct_reg_status_idx"),
            models.Index(fields=("expires_at",), name="acct_reg_exp_idx"),
        ]


class UserInvite(models.Model):
    """Invite record for code-based team member onboarding."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REVOKED = "revoked"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REVOKED, "Revoked"),
        (STATUS_EXPIRED, "Expired"),
    )

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="user_invites")
    invited_by = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="user_invites_created",
    )
    invite_name = models.CharField(max_length=200)
    invite_name_enc = models.TextField(blank=True, default="")
    invite_email = models.EmailField()
    role = models.CharField(max_length=32, choices=User.ROLE_CHOICES)
    manager = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_invites_managed",
    )
    invite_code_hash = models.CharField(max_length=128)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(
        "User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    last_sent_at = models.DateTimeField(default=timezone.now)
    resend_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=("agency", "status", "expires_at"), name="acct_inv_status_idx"),
            models.Index(fields=("invite_email", "status"), name="acct_inv_email_idx"),
            models.Index(
                fields=("agency", "status", "created_at", "id"),
                name="acct_inv_page_idx",
            ),
            models.Index(
                fields=("agency", "status", "manager", "created_at", "id"),
                name="acct_inv_mgr_page_idx",
            ),
            models.Index(
                fields=("agency", "status", "invited_by", "created_at", "id"),
                name="acct_inv_ib_page_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(role=User.ROLE_AGENT) & Q(manager__isnull=False))
                    | (Q(role=User.ROLE_MANAGER) & Q(manager__isnull=True))
                ),
                name="acct_inv_role_manager_ck",
            )
        ]


class EmailOutbox(models.Model):
    """Persistent outbound email queue for guaranteed-delivery retries."""

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED_PERMANENT = "failed_permanent"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED_PERMANENT, "Failed Permanent"),
    )

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    to_email = models.EmailField()
    subject = models.CharField(max_length=500)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("status", "created_at"), name="email_outbox_status_idx"),
        ]


class DiagnosticsSigningKey(models.Model):
    """Per-device diagnostics verification public keys for support workflows."""

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="diagnostics_keys")
    device_id = models.CharField(max_length=128)
    signature_key_id = models.CharField(max_length=128)
    public_key = models.TextField()
    is_active = models.BooleanField(default=True)
    enrolled_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diagnostics_keys_enrolled",
    )
    approved_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diagnostics_keys_approved",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("agency", "device_id", "signature_key_id"),)
        indexes = [
            models.Index(
                fields=("agency", "device_id", "is_active"),
                name="acct_diag_key_act_idx",
            ),
            models.Index(
                fields=("agency", "signature_key_id"),
                name="acct_diag_key_sig_idx",
            ),
        ]


class UserSession(models.Model):
    """Tracked JWT-backed user sessions for list/revoke controls."""

    session_id = models.UUIDField(default=uuid4, editable=False, unique=True)
    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="auth_sessions",
    )
    agency = models.ForeignKey(
        Agency,
        on_delete=models.CASCADE,
        related_name="user_sessions",
        null=True,
        blank=True,
    )
    source_ip = models.CharField(max_length=64, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    refresh_jti = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("user", "revoked_at"), name="acct_user_sess_user_idx"),
            models.Index(fields=("expires_at",), name="acct_user_sess_exp_idx"),
            models.Index(fields=("agency", "revoked_at"), name="acct_user_sess_ag_idx"),
        ]


class PrivilegeElevationRequest(models.Model):
    """Time-bound privilege elevation with approval workflow."""

    PERMISSION_CAN_IMPORT = "can_import"
    PERMISSION_CAN_HARD_DELETE = "can_hard_delete"
    PERMISSION_CHOICES = (
        (PERMISSION_CAN_IMPORT, "Can import"),
        (PERMISSION_CAN_HARD_DELETE, "Can hard delete"),
    )

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DENIED, "Denied"),
        (STATUS_REVOKED, "Revoked"),
    )

    agency = models.ForeignKey(
        Agency,
        on_delete=models.CASCADE,
        related_name="privilege_requests",
    )
    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="privilege_requests",
    )
    permission = models.CharField(max_length=64, choices=PERMISSION_CHOICES)
    reason = models.CharField(max_length=512, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="privilege_requests_created",
    )
    approved_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="privilege_requests_approved",
    )
    revoked_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="privilege_requests_revoked",
    )
    requested_at = models.DateTimeField(default=timezone.now, editable=False)
    decided_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=256, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("agency", "status", "permission"),
                name="acct_priv_req_status_idx",
            ),
            models.Index(
                fields=("user", "status", "expires_at"),
                name="acct_priv_req_user_idx",
            ),
        ]


class DiagnosticsEnrollmentToken(models.Model):
    """One-time enrollment token for diagnostics key registration."""

    token_id = models.UUIDField(default=uuid4, editable=False, unique=True)
    agency = models.ForeignKey(
        Agency,
        on_delete=models.CASCADE,
        related_name="diagnostics_enrollment_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    device_id = models.CharField(max_length=128, blank=True)
    issued_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diagnostics_tokens_issued",
    )
    consumed_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diagnostics_tokens_consumed",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("agency", "expires_at"), name="acct_diag_tok_exp_idx"),
            models.Index(fields=("agency", "consumed_at"), name="acct_diag_tok_use_idx"),
        ]


class UserActionToken(models.Model):
    """One-time tokens for account activation and password reset workflows."""

    PURPOSE_INVITE_ACTIVATION = "invite_activation"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_CHOICES = (
        (PURPOSE_INVITE_ACTIVATION, "Invite Activation"),
        (PURPOSE_PASSWORD_RESET, "Password Reset"),
    )

    token_id = models.UUIDField(default=uuid4, editable=False, unique=True)
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=32, choices=PURPOSE_CHOICES)
    agency = models.ForeignKey(
        Agency,
        on_delete=models.CASCADE,
        related_name="user_action_tokens",
    )
    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="action_tokens",
    )
    issued_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_tokens_issued",
    )
    consumed_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_tokens_consumed",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("agency", "purpose", "expires_at"), name="acct_uat_exp_idx"),
            models.Index(fields=("agency", "purpose", "consumed_at"), name="acct_uat_use_idx"),
            models.Index(fields=("user", "purpose"), name="acct_uat_user_idx"),
        ]


class ComplianceJob(models.Model):
    """Asynchronous compliance export/delete workflow job."""

    TYPE_EXPORT = "export"
    TYPE_DELETE = "delete"
    TYPE_CHOICES = (
        (TYPE_EXPORT, "Export"),
        (TYPE_DELETE, "Delete"),
    )

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = (
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
    )
    ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)

    job_id = models.UUIDField(default=uuid4, editable=False, unique=True)
    agency = models.ForeignKey(
        Agency,
        on_delete=models.CASCADE,
        related_name="compliance_jobs",
    )
    target_user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="compliance_jobs_targeted",
    )
    requested_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compliance_jobs_requested",
    )
    job_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    step_up_verified_at = models.DateTimeField()
    payload_json = models.JSONField(default=dict, blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=128, blank=True)
    artifact_path = models.CharField(max_length=512, blank=True)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    artifact_size_bytes = models.BigIntegerField(default=0)
    artifact_content_type = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("agency", "job_type", "status", "created_at"),
                name="acct_comp_job_status_idx",
            ),
            models.Index(fields=("expires_at",), name="acct_comp_job_exp_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("agency", "target_user", "job_type"),
                condition=Q(status__in=("queued", "running")),
                name="acct_comp_job_one_active",
            )
        ]
