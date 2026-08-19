from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

SchemaOwner = Literal["alembic_physical", "django_physical"]
MirrorStrategy = Literal["none", "django_native", "state_only_mirror"]
SchemaObjectKind = Literal["table", "index", "constraint"]


@dataclass(frozen=True)
class SchemaTableContract:
    table_name: str
    owner: SchemaOwner
    mirror_strategy: MirrorStrategy
    orm_model: str | None
    creating_alembic_revision: str | None
    creating_django_migration: str | None
    notes: str = ""


_SCHEMA_TABLE_CONTRACTS: tuple[SchemaTableContract, ...] = (
    SchemaTableContract(
        table_name="accounts_agency",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.Agency",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_compliancejob",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.ComplianceJob",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_diagnosticsenrollmenttoken",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.DiagnosticsEnrollmentToken",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_diagnosticssigningkey",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.DiagnosticsSigningKey",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_emailoutbox",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.EmailOutbox",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_privilegeelevationrequest",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.PrivilegeElevationRequest",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_registrationrequest",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.RegistrationRequest",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_user",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.User",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_useractiontoken",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.UserActionToken",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_userinvite",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.UserInvite",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="accounts_usersession",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="accounts.UserSession",
        creating_alembic_revision=None,
        creating_django_migration="accounts (django-native app table)",
    ),
    SchemaTableContract(
        table_name="actions",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="agency_settings",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="api_idempotency_records",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="api_rebuild_job_leases",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="audit_logs",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="auth_group",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="auth.Group",
        creating_alembic_revision=None,
        creating_django_migration="django.contrib.auth (framework-managed)",
    ),
    SchemaTableContract(
        table_name="auth_permission",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="auth.Permission",
        creating_alembic_revision=None,
        creating_django_migration="django.contrib.auth (framework-managed)",
    ),
    SchemaTableContract(
        table_name="auth_security_events",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="clients",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="contract_articles",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="contracts",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="custom_locations",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="demande_locations",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="demandes",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="django_admin_log",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="admin.LogEntry",
        creating_alembic_revision=None,
        creating_django_migration="django.contrib.admin (framework-managed)",
    ),
    SchemaTableContract(
        table_name="django_content_type",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="contenttypes.ContentType",
        creating_alembic_revision=None,
        creating_django_migration="django.contrib.contenttypes (framework-managed)",
    ),
    SchemaTableContract(
        table_name="django_migrations",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model=None,
        creating_alembic_revision=None,
        creating_django_migration="django migration recorder (framework-managed)",
    ),
    SchemaTableContract(
        table_name="django_session",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="sessions.Session",
        creating_alembic_revision=None,
        creating_django_migration="django.contrib.sessions (framework-managed)",
    ),
    SchemaTableContract(
        table_name="imports_importagencyalias",
        owner="alembic_physical",
        mirror_strategy="state_only_mirror",
        orm_model="imports.ImportAgencyAlias",
        creating_alembic_revision="20260313_0026",
        creating_django_migration="imports.0007_importagencyalias_importcorrectionsignal",
    ),
    SchemaTableContract(
        table_name="imports_importagencyprofile",
        owner="alembic_physical",
        mirror_strategy="state_only_mirror",
        orm_model="imports.ImportAgencyProfile",
        creating_alembic_revision="20260313_0027",
        creating_django_migration="imports.0008_importagencyprofile_importdeadletterrow",
    ),
    SchemaTableContract(
        table_name="imports_importartifactmanifest",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="imports.ImportArtifactManifest",
        creating_alembic_revision=None,
        creating_django_migration="imports (django-native app table)",
    ),
    SchemaTableContract(
        table_name="imports_importchunk",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="imports.ImportChunk",
        creating_alembic_revision=None,
        creating_django_migration="imports (django-native app table)",
    ),
    SchemaTableContract(
        table_name="imports_importchunkphase",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="imports.ImportChunkPhase",
        creating_alembic_revision=None,
        creating_django_migration="imports (django-native app table)",
        notes=(
            "Legacy Django-owned table. Alembic revision 20260312_0025 bridge-adds "
            "heartbeat_at when absent, but table ownership remains Django."
        ),
    ),
    SchemaTableContract(
        table_name="imports_importcorrectionsignal",
        owner="alembic_physical",
        mirror_strategy="state_only_mirror",
        orm_model="imports.ImportCorrectionSignal",
        creating_alembic_revision="20260313_0026",
        creating_django_migration="imports.0007_importagencyalias_importcorrectionsignal",
    ),
    SchemaTableContract(
        table_name="imports_importdeadletterrow",
        owner="alembic_physical",
        mirror_strategy="state_only_mirror",
        orm_model="imports.ImportDeadLetterRow",
        creating_alembic_revision="20260313_0027",
        creating_django_migration="imports.0008_importagencyprofile_importdeadletterrow",
    ),
    SchemaTableContract(
        table_name="imports_importjob",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="imports.ImportJob",
        creating_alembic_revision=None,
        creating_django_migration="imports (django-native app table)",
    ),
    SchemaTableContract(
        table_name="imports_importreviewgroup",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="imports.ImportReviewGroup",
        creating_alembic_revision=None,
        creating_django_migration="imports (django-native app table)",
    ),
    SchemaTableContract(
        table_name="imports_importreviewitem",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="imports.ImportReviewItem",
        creating_alembic_revision=None,
        creating_django_migration="imports (django-native app table)",
    ),
    SchemaTableContract(
        table_name="imports_importrowaudit",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="imports.ImportRowAudit",
        creating_alembic_revision=None,
        creating_django_migration="imports (django-native app table)",
    ),
    SchemaTableContract(
        table_name="imports_importworkflowstate",
        owner="alembic_physical",
        mirror_strategy="state_only_mirror",
        orm_model="imports.ImportWorkflowState",
        creating_alembic_revision="20260312_0025",
        creating_django_migration="imports.0006_importworkflowstate_importchunkphase_heartbeat_at",
        notes="Legacy bridge table reconciled as Alembic physical truth plus Django state mirror.",
    ),
    SchemaTableContract(
        table_name="listings",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="locations",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="match_candidates",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="match_counts_cache",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="match_artifact_health_samples",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="20260330_0030",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="match_artifact_timeout_counters",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="20260330_0030",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="match_pairs",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="match_rebuild_state",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="surface_cache_generation",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="20260330_0029",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="meta",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="notification_reads",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="notifications",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="offer_locations",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="offer_photos",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="offers",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="property_types",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="record_acl",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="storage_events",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="storage_objects",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="storage_usage",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="task_failures",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="task_scan_checkpoints",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="tenant_work_lease",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="token_blacklist_blacklistedtoken",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="token_blacklist.BlacklistedToken",
        creating_alembic_revision=None,
        creating_django_migration="rest_framework_simplejwt.token_blacklist (framework-managed)",
    ),
    SchemaTableContract(
        table_name="token_blacklist_outstandingtoken",
        owner="django_physical",
        mirror_strategy="django_native",
        orm_model="token_blacklist.OutstandingToken",
        creating_alembic_revision=None,
        creating_django_migration="rest_framework_simplejwt.token_blacklist (framework-managed)",
    ),
    SchemaTableContract(
        table_name="visits",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="wa_templates",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
    SchemaTableContract(
        table_name="wilayas",
        owner="alembic_physical",
        mirror_strategy="none",
        orm_model=None,
        creating_alembic_revision="bootstrap_ahead_of_tracked_revisions",
        creating_django_migration=None,
    ),
)


def iter_schema_table_contracts() -> tuple[SchemaTableContract, ...]:
    return _SCHEMA_TABLE_CONTRACTS


@lru_cache(maxsize=1)
def schema_table_contracts_by_name() -> dict[str, SchemaTableContract]:
    return {contract.table_name: contract for contract in _SCHEMA_TABLE_CONTRACTS}


def get_schema_table_contract(table_name: str) -> SchemaTableContract:
    return schema_table_contracts_by_name()[table_name]


def iter_contracts_by_owner(owner: SchemaOwner) -> tuple[SchemaTableContract, ...]:
    return tuple(contract for contract in _SCHEMA_TABLE_CONTRACTS if contract.owner == owner)


def iter_state_only_mirror_contracts() -> tuple[SchemaTableContract, ...]:
    return tuple(
        contract
        for contract in _SCHEMA_TABLE_CONTRACTS
        if contract.mirror_strategy == "state_only_mirror"
    )
